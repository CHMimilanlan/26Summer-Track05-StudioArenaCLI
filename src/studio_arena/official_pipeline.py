"""Run the Studio Arena official two-stage pipeline.

This module is intentionally standalone so Synergy master can execute it from an
agenda item with a single Python command. It owns process orchestration: stage 1
runs in parallel, Anima summarization starts in the background, and stage 2 runs
in parallel immediately after stage 1 succeeds.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_RANGES = [(0, 10), (10, 20), (20, 30), (30, 35)]
DEFAULT_TASK_DIR = Path("/inspire/qb-ilm2/project/26summer-camp-05/26210305")


@dataclass
class ProcessResult:
    name: str
    command: list[str]
    pid: int
    returncode: int
    stdout_log: str
    stderr_log: str
    duration_seconds: float


def _now_ms() -> int:
    return int(time.time() * 1000)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_task_dir() -> Path:
    if DEFAULT_TASK_DIR.exists():
        return DEFAULT_TASK_DIR
    return _workspace_root() / "Task"


def _parse_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" not in item:
            raise ValueError(f"Invalid range {item!r}; expected START-END")
        start, end = item.split("-", 1)
        ranges.append((int(start), int(end)))
    if not ranges:
        raise ValueError("At least one range is required")
    return ranges


def _open_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", errors="replace")


def _registry_path(task_dir: Path) -> Path:
    return task_dir.resolve() / "logs" / "official_pipeline_active.json"


def _read_registry(task_dir: Path) -> dict[str, Any]:
    path = _registry_path(task_dir)
    if not path.exists():
        return {"runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}
    if not isinstance(data, dict):
        return {"runs": []}
    data.setdefault("runs", [])
    return data


def _write_registry(task_dir: Path, data: dict[str, Any]) -> None:
    path = _registry_path(task_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _process_cmdline(pid: int) -> str:
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            return proc_cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except OSError:
            return ""
    return ""


def _refresh_registry(task_dir: Path) -> dict[str, Any]:
    data = _read_registry(task_dir)
    changed = False
    for run in data.get("runs", []):
        for proc in run.get("processes", []):
            status = proc.get("status")
            if status in {"exited", "terminated"}:
                continue
            pid = int(proc.get("pid") or 0)
            alive = _is_pid_alive(pid)
            proc["alive"] = alive
            if not alive and status == "running":
                proc["status"] = "exited"
                proc["ended_at"] = _now_ms()
                changed = True
    if changed:
        _write_registry(task_dir, data)
    return data


def _upsert_run(task_dir: Path, run: dict[str, Any]) -> None:
    data = _read_registry(task_dir)
    runs = data.setdefault("runs", [])
    for idx, existing in enumerate(runs):
        if existing.get("run_id") == run.get("run_id"):
            runs[idx] = run
            break
    else:
        runs.append(run)
    _write_registry(task_dir, data)


def _register_process(
    task_dir: Path,
    run_id: str,
    name: str,
    command: Sequence[str],
    proc: subprocess.Popen,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    data = _read_registry(task_dir)
    runs = data.setdefault("runs", [])
    run = next((item for item in runs if item.get("run_id") == run_id), None)
    if run is None:
        run = {
            "run_id": run_id,
            "main_pid": os.getpid(),
            "task_dir": str(task_dir.resolve()),
            "status": "running",
            "started_at": _now_ms(),
            "processes": [],
        }
        runs.append(run)

    processes = run.setdefault("processes", [])
    processes.append(
        {
            "name": name,
            "pid": proc.pid,
            "command": list(command),
            "command_text": " ".join(str(part) for part in command),
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "status": "running",
            "alive": True,
            "started_at": _now_ms(),
            "process_group": proc.pid if os.name != "nt" else None,
        }
    )
    _write_registry(task_dir, data)


def _mark_process_exited(task_dir: Path, run_id: str, pid: int, returncode: int) -> None:
    data = _read_registry(task_dir)
    for run in data.get("runs", []):
        if run.get("run_id") != run_id:
            continue
        for proc in run.get("processes", []):
            if proc.get("pid") == pid:
                proc["status"] = "exited"
                proc["alive"] = False
                proc["returncode"] = returncode
                proc["ended_at"] = _now_ms()
                break
    _write_registry(task_dir, data)


def _mark_run_status(task_dir: Path, run_id: str, status: str) -> None:
    data = _read_registry(task_dir)
    for run in data.get("runs", []):
        if run.get("run_id") == run_id:
            run["status"] = status
            run["updated_at"] = _now_ms()
            if status in {"completed", "failed", "terminated"}:
                run["ended_at"] = _now_ms()
            break
    _write_registry(task_dir, data)


def list_registered_processes(task_dir: Path) -> dict[str, Any]:
    return _refresh_registry(task_dir)


def _terminate_pid(pid: int, *, process_group: bool, force: bool) -> bool:
    if not _is_pid_alive(pid):
        return False
    if os.name == "nt":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return not _is_pid_alive(pid)

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        if process_group:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        return False
    except OSError:
        if process_group:
            os.kill(pid, sig)
    return True


def stop_registered_processes(
    task_dir: Path,
    *,
    pid: int | None = None,
    name: str | None = None,
    run_id: str | None = None,
    all_processes: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not any([pid is not None, name, run_id, all_processes]):
        raise ValueError("Choose a target: pid, name, run_id, or all_processes=True")

    data = _refresh_registry(task_dir)
    stopped = []
    skipped = []

    for run in data.get("runs", []):
        if run_id and run.get("run_id") != run_id:
            continue
        run_scope_all = bool(run_id and pid is None and name is None and not all_processes)
        for proc in run.get("processes", []):
            proc_pid = int(proc.get("pid") or 0)
            matches = all_processes or run_scope_all
            matches = matches or (pid is not None and proc_pid == pid)
            matches = matches or (name is not None and proc.get("name") == name)
            if not matches:
                continue

            if not _is_pid_alive(proc_pid):
                skipped.append({"pid": proc_pid, "name": proc.get("name"), "reason": "not running"})
                proc["alive"] = False
                if proc.get("status") == "running":
                    proc["status"] = "exited"
                continue

            _terminate_pid(proc_pid, process_group=bool(proc.get("process_group")), force=force)
            proc["status"] = "terminated"
            proc["alive"] = _is_pid_alive(proc_pid)
            proc["terminated_at"] = _now_ms()
            stopped.append({"pid": proc_pid, "name": proc.get("name"), "alive": proc["alive"]})

    _write_registry(task_dir, data)
    return {"stopped": stopped, "skipped": skipped, "registry": str(_registry_path(task_dir))}


def _popen_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _run_parallel(
    specs: Iterable[tuple[str, Sequence[str]]],
    *,
    cwd: Path,
    log_dir: Path,
    env: dict[str, str],
    task_dir: Path,
    run_id: str,
) -> list[ProcessResult]:
    running = []
    starts: dict[str, float] = {}

    for name, command in specs:
        stdout_path = log_dir / f"{name}.stdout.log"
        stderr_path = log_dir / f"{name}.stderr.log"
        stdout_file = _open_log(stdout_path)
        stderr_file = _open_log(stderr_path)
        print(f"[start] {name}: {' '.join(command)}")
        proc = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            **_popen_kwargs(),
        )
        _register_process(task_dir, run_id, name, command, proc, stdout_path, stderr_path)
        starts[name] = time.time()
        running.append((name, list(command), proc, stdout_file, stderr_file, stdout_path, stderr_path))

    results: list[ProcessResult] = []
    for name, command, proc, stdout_file, stderr_file, stdout_path, stderr_path in running:
        returncode = proc.wait()
        stdout_file.close()
        stderr_file.close()
        duration = time.time() - starts[name]
        print(f"[done] {name}: returncode={returncode} duration={duration:.1f}s")
        _mark_process_exited(task_dir, run_id, proc.pid, returncode)
        results.append(
            ProcessResult(
                name=name,
                command=command,
                pid=proc.pid,
                returncode=returncode,
                stdout_log=str(stdout_path),
                stderr_log=str(stderr_path),
                duration_seconds=duration,
            )
        )

    return results


def _check_success(results: list[ProcessResult], stage: str) -> None:
    failed = [item for item in results if item.returncode != 0]
    if failed:
        detail = "\n".join(
            f"- {item.name}: returncode={item.returncode}, stderr={item.stderr_log}" for item in failed
        )
        raise RuntimeError(f"{stage} failed:\n{detail}")


def _state_name(prefix: str, start: int, end: int) -> str:
    return f"{prefix}_{start}_{end}.json"


def run_pipeline(
    *,
    task_dir: Path,
    ranges: list[tuple[int, int]],
    log_dir: Path,
    python_executable: str,
    use_synergy: bool,
    skip_anima: bool,
) -> dict:
    task_dir = task_dir.resolve()
    log_dir = log_dir.resolve()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    started = time.time()
    run_id = time.strftime("official_pipeline_%Y%m%d_%H%M%S") + f"_{os.getpid()}"
    print(f"[pipeline] task_dir={task_dir}")
    print(f"[pipeline] log_dir={log_dir}")
    print(f"[pipeline] run_id={run_id}")

    _upsert_run(
        task_dir,
        {
            "run_id": run_id,
            "main_pid": os.getpid(),
            "task_dir": str(task_dir),
            "log_dir": str(log_dir),
            "status": "running",
            "started_at": _now_ms(),
            "processes": [],
        },
    )

    stage1_specs = []
    for start, end in ranges:
        output_state = _state_name("official", start, end)
        command = [
            python_executable,
            "workflow_officail_stage1.py",
            "--start",
            str(start),
            "--end",
            str(end),
            "--output-state",
            output_state,
        ]
        if use_synergy:
            command.append("--use-synergy")
        stage1_specs.append((f"stage1_{start}_{end}", command))

    stage1_results = _run_parallel(
        stage1_specs,
        cwd=task_dir,
        log_dir=log_dir,
        env=env,
        task_dir=task_dir,
        run_id=run_id,
    )
    _check_success(stage1_results, "stage1")

    missing_inputs = []
    for start, end in ranges:
        output_state = task_dir / _state_name("official", start, end)
        if not output_state.exists():
            missing_inputs.append(str(output_state))
    if missing_inputs:
        raise RuntimeError("Stage1 succeeded but expected state files are missing:\n" + "\n".join(missing_inputs))

    anima_proc = None
    if not skip_anima:
        stdout_path = log_dir / "anima_summerizer.stdout.log"
        stderr_path = log_dir / "anima_summerizer.stderr.log"
        print("[start] anima_summerizer: python workflow_anima_summerizer.py")
        anima_proc = subprocess.Popen(
            [python_executable, "workflow_anima_summerizer.py"],
            cwd=str(task_dir),
            env=env,
            stdout=_open_log(stdout_path),
            stderr=_open_log(stderr_path),
            text=True,
            **_popen_kwargs(),
        )
        _register_process(
            task_dir,
            run_id,
            "anima_summerizer",
            [python_executable, "workflow_anima_summerizer.py"],
            anima_proc,
            stdout_path,
            stderr_path,
        )

    stage2_specs = []
    for start, end in ranges:
        input_state = _state_name("official", start, end)
        output_state = _state_name("official_output", start, end)
        command = [
            python_executable,
            "workflow_officail_stage2.py",
            "--start",
            str(start),
            "--end",
            str(end),
            "--input-state",
            input_state,
            "--output-state",
            output_state,
        ]
        stage2_specs.append((f"stage2_{start}_{end}", command))

    stage2_results = _run_parallel(
        stage2_specs,
        cwd=task_dir,
        log_dir=log_dir,
        env=env,
        task_dir=task_dir,
        run_id=run_id,
    )
    _check_success(stage2_results, "stage2")

    missing_outputs = []
    for start, end in ranges:
        output_state = task_dir / _state_name("official_output", start, end)
        if not output_state.exists():
            missing_outputs.append(str(output_state))
    if missing_outputs:
        raise RuntimeError("Stage2 succeeded but expected output files are missing:\n" + "\n".join(missing_outputs))

    _mark_run_status(task_dir, run_id, "completed")

    return {
        "ok": True,
        "run_id": run_id,
        "task_dir": str(task_dir),
        "log_dir": str(log_dir),
        "registry": str(_registry_path(task_dir)),
        "ranges": ranges,
        "stage1": [item.__dict__ for item in stage1_results],
        "stage2": [item.__dict__ for item in stage2_results],
        "anima": {
            "started": anima_proc is not None,
            "pid": anima_proc.pid if anima_proc else None,
            "not_waited": anima_proc is not None,
        },
        "duration_seconds": time.time() - started,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the official Stage1 -> Anima -> Stage2 pipeline.")
    parser.add_argument("--task-dir", default=str(_default_task_dir()), help="Directory containing workflow scripts")
    parser.add_argument("--ranges", default="0-10,10-20,20-30,30-35", help="Comma separated START-END ranges")
    parser.add_argument("--log-dir", default="", help="Directory for child process logs")
    parser.add_argument("--python", default=sys.executable, help="Python executable used for child workflow scripts")
    parser.add_argument("--no-use-synergy", action="store_true", help="Do not pass --use-synergy to stage1")
    parser.add_argument("--skip-anima", action="store_true", help="Do not start workflow_anima_summerizer.py")
    parser.add_argument("--json-output", action="store_true", help="Print JSON summary only")
    args = parser.parse_args(argv)

    task_dir = Path(args.task_dir)
    log_dir = Path(args.log_dir) if args.log_dir else task_dir / "logs" / time.strftime("official_pipeline_%Y%m%d_%H%M%S")

    try:
        summary = run_pipeline(
            task_dir=task_dir,
            ranges=_parse_ranges(args.ranges),
            log_dir=log_dir,
            python_executable=args.python,
            use_synergy=not args.no_use_synergy,
            skip_anima=args.skip_anima,
        )
    except Exception as exc:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
