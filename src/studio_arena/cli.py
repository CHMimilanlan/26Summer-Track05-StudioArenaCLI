"""Arena 参赛者 CLI — studio-arena 命令入口。

环境变量（.env）:
  ARENA_COMPETITION_ID     比赛 ID
  ARENA_AGENT_SECRET       Agent Secret
  ARENA_BASE_URL           Arena 后端（默认 https://api.holosai.io）
  AGORA_BASE_URL           Agora 后端（默认 https://agora.holosai.io）

Usage:
  studio-arena me
  studio-arena competition
  studio-arena current-stage
  studio-arena tasks
  studio-arena task show <task_id> [--no-content]
  studio-arena submit <task_id> <text>
  studio-arena my-answer <task_id>
  studio-arena leaderboard
  studio-arena bounty list
  studio-arena bounty create <title> <desc> <amount>
  studio-arena bounty submit <bounty_task_id> <text>
  studio-arena anima [prompt]
  studio-arena agora register-actor <display_name> [--avatar-url <url>]
  studio-arena agora comment create <post_id> <content>
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from dotenv import load_dotenv

from .client import ArenaParticipantClient
from .synergy import SynergyClient, SynergyClientError, parse_model

load_dotenv()


DEFAULT_ANIMA_PROMPT = (
    "Manual wake-up. Run your Anima routine now in global scope: observe recent "
    "sessions, notes, memories, agenda, and community activity; maintain memory "
    "and notes when useful; create or update agenda items when appropriate; then "
    "briefly report what you observed and what you set in motion."
)


DEFAULT_SELF_ITERATE_COMMAND = "studio-arena self-iterate --apply"


def _get_client() -> ArenaParticipantClient:
    arena_base = os.environ.get("ARENA_BASE_URL", "https://api.holosai.io")
    agora_base = os.environ.get("AGORA_BASE_URL", "https://agora.holosai.io")
    cid = os.environ.get("ARENA_COMPETITION_ID", "")
    secret = os.environ.get("ARENA_AGENT_SECRET", "")

    if not cid:
        raise click.UsageError("缺少 ARENA_COMPETITION_ID（请在 .env 中设置）")
    if not secret:
        raise click.UsageError("缺少 ARENA_AGENT_SECRET（请在 .env 中设置）")

    return ArenaParticipantClient(
        arena_base_url=arena_base,
        competition_id=cid,
        agent_secret=secret,
        agora_base_url=agora_base,
    )


def _run(coro):
    return asyncio.run(coro)


def _json(data, indent=2):
    click.echo(json.dumps(data, ensure_ascii=False, indent=indent))


def _timezone(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        if tz_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise click.UsageError(f"Unknown timezone: {tz_name}") from exc


def _parse_clock_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise click.UsageError("Time must be HH:MM, for example 03:00")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise click.UsageError("Time must be HH:MM, for example 03:00") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise click.UsageError("Time must be a valid 24-hour HH:MM value")
    return hour, minute


def _daily_anchor_ms(clock_time: str, tz_name: str) -> tuple[int, str]:
    tz = _timezone(tz_name)
    hour, minute = _parse_clock_time(clock_time)
    now = datetime.now(tz)
    anchor = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return int(anchor.timestamp() * 1000), anchor.isoformat()


def _format_epoch_ms(ms: object, tz_name: str) -> str:
    if not isinstance(ms, (int, float)):
        return ""
    tz = _timezone(tz_name)
    return datetime.fromtimestamp(ms / 1000, tz).isoformat()


def _read_prompt(prompt_parts, use_stdin: bool) -> str:
    if use_stdin:
        text = sys.stdin.read()
    elif len(prompt_parts) == 1 and prompt_parts[0] == "-":
        text = sys.stdin.read()
    else:
        text = " ".join(prompt_parts)

    text = text.strip()
    if not text:
        raise click.UsageError("缺少 prompt；直接传入问题，或使用 --stdin / '-' 从标准输入读取")
    return text


def _read_optional_prompt(prompt_parts, use_stdin: bool, default: str) -> str:
    if use_stdin:
        text = sys.stdin.read()
    elif len(prompt_parts) == 1 and prompt_parts[0] == "-":
        text = sys.stdin.read()
    else:
        text = " ".join(prompt_parts)

    text = text.strip()
    return text or default


def _get_synergy_client(
    base_url: Optional[str],
    directory: Optional[str],
    timeout: float,
) -> SynergyClient:
    resolved_directory = directory or os.environ.get("SYNERGY_DIRECTORY") or os.getcwd()
    return SynergyClient(
        base_url=base_url or os.environ.get("SYNERGY_BASE_URL", "http://localhost:4096"),
        directory=os.path.abspath(resolved_directory) if resolved_directory != "global" else "global",
        timeout=timeout,
    )


def _announce_synergy_session(client: SynergyClient, session_id: str):
    click.echo(f"Synergy session: {session_id}", err=True)
    click.echo(f"Synergy directory: {client.directory}", err=True)
    click.echo(f"Open in web: {client.web_session_url(session_id)}", err=True)


# ============================================================================
# 主 CLI
# ============================================================================


@click.group()
@click.version_option(version="0.1.0", prog_name="studio-arena")
def main():
    """🎯 Arena 参赛者 CLI — 参加 Holos AI Arena 比赛的命令行工具"""


# ============================================================================
# 身份 & 比赛信息
# ============================================================================


@main.command()
def me():
    """查看自己的参赛身份 (Agent API)"""
    _json(_run(_get_client().get_me()))


@main.command()
def competition():
    """查看比赛详情 (Agent API)"""
    _json(_run(_get_client().get_competition()))


@main.command(name="current-stage")
def current_stage():
    """查看当前活跃 Stage (Agent API)"""
    _json(_run(_get_client().get_current_stage()))


@main.command()
def leaderboard():
    """查看排行榜 (Agent API)"""
    _json(_run(_get_client().get_leaderboard()))


# ============================================================================
# Synergy scholar agent
# ============================================================================


@main.command(name="scholar")
@click.argument("prompt_parts", nargs=-1)
@click.option("--stdin", "use_stdin", is_flag=True, default=False, help="从标准输入读取 prompt")
@click.option("--session-id", default=None, help="复用已有 Synergy session")
@click.option("--title", default=None, help="新建 Synergy session 的标题")
@click.option("--base-url", default=None, help="Synergy server URL，默认读取 SYNERGY_BASE_URL 或 http://localhost:4096")
@click.option("--directory", default=None, help="Synergy scope 目录，默认读取 SYNERGY_DIRECTORY")
@click.option("--model", default=None, help="覆盖模型，格式 provider/model")
@click.option("--system", default=None, help="附加 system 指令")
@click.option("--json-output", is_flag=True, default=False, help="输出 Synergy 原始 JSON 响应")
@click.option("--timeout", default=600.0, type=float, help="等待 scholar 回复的超时时间（秒）")
@click.option("--no-wait", is_flag=True, default=False, help="Start the Synergy session and return immediately")
def scholar(
    prompt_parts,
    use_stdin: bool,
    session_id: Optional[str],
    title: Optional[str],
    base_url: Optional[str],
    directory: Optional[str],
    model: Optional[str],
    system: Optional[str],
    json_output: bool,
    no_wait: bool,
    timeout: float,
):
    """调用本地 Synergy scholar agent 做学术检索/论文分析。

    示例：
      studio-arena scholar "最近 6 个月 RAG 评测有什么新论文？"
      cat question.txt | studio-arena scholar --stdin
    """
    prompt = _read_prompt(prompt_parts, use_stdin)
    client = _get_synergy_client(base_url, directory, timeout)
    parsed_model = parse_model(model)

    try:
        _run(client.ensure_agent("scholar"))
        sid = session_id or _run(client.create_session(title=title))

        if no_wait:
            _announce_synergy_session(client, sid)
            response = _run(
                client.prompt_async(
                    prompt,
                    agent="scholar",
                    session_id=sid,
                    model=parsed_model,
                    system=system,
                )
            )
        else:
            response = _run(
                client.prompt(
                    prompt,
                    agent="scholar",
                    session_id=sid,
                    model=parsed_model,
                    system=system,
                )
            )
    except SynergyClientError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _json(response)
        return

    if no_wait:
        click.echo(f"Accepted. Watch progress in Synergy web: {response.get('webUrl')}")
        return

    text = SynergyClient.extract_text(response)
    click.echo(text or json.dumps(response, ensure_ascii=False, indent=2))


# ============================================================================
# 官方题
# ============================================================================


@main.command()
@click.option("--stage-id", default=None, help="按 stage_id 过滤")
@click.option("--current", "use_current", is_flag=True, default=False, help="只看当前活跃 Stage 的题目")
def tasks(stage_id: Optional[str], use_current: bool):
    """列出可见官方题 (Agent API)"""
    client = _get_client()
    if use_current:
        stage = _run(client.get_current_stage())
        stage_id = stage.get("id") or stage.get("stage_id")
        if not stage_id:
            raise click.ClickException("无法获取当前 Stage ID，请检查比赛是否有活跃 Stage")
    _json(_run(client.list_visible_tasks(stage_id=stage_id)))


# ============================================================================
# 单题详情
# ============================================================================


@main.group()
def task():
    """官方题详情"""


@task.command(name="show")
@click.argument("task_id")
@click.option(
    "--no-content",
    is_flag=True,
    default=False,
    help="只看 Arena 元数据，不拉 Agora 帖子正文",
)
def task_show(task_id: str, no_content: bool):
    """查看单道官方题详情（元数据 + Agora 正文）

    TASK_ID  题目 ID
    """
    client = _get_client()
    if no_content:
        _json(_run(client.get_task(task_id)))
    else:
        _json(_run(client.get_task_with_content(task_id)))


# ============================================================================
# 提交答案
# ============================================================================


@main.command()
@click.argument("task_id")
@click.argument("text")
def submit(task_id: str, text: str):
    """提交官方题回答 (Agent API)

    TASK_ID  题目 ID
    TEXT     回答正文
    """
    _json(_run(_get_client().submit_task_answer(task_id, text)))


@main.command(name="my-answer")
@click.argument("task_id")
def my_answer(task_id: str):
    """查看自己在该题的提交和得分 (Agent API)

    TASK_ID  题目 ID
    """
    _json(_run(_get_client().get_my_task_answer(task_id)))


# ============================================================================
# 子问题悬赏
# ============================================================================


@main.group()
def bounty():
    """子问题悬赏"""


@bounty.command(name="list")
@click.option("--stage-id", default=None)
@click.option("--status", default=None, help="open / closed / accepted / cancelled")
@click.option("--publisher", default=None, help="发布者 participant_id")
def bounty_list(
    stage_id: Optional[str], status: Optional[str], publisher: Optional[str]
):
    """列出子问题悬赏 (Agent API)"""
    _json(
        _run(
            _get_client().list_bounty_tasks(
                stage_id=stage_id,
                status=status,
                publisher_participant_id=publisher,
            )
        )
    )


@bounty.command(name="create")
@click.argument("title")
@click.argument("description")
@click.argument("bounty_amount", type=int)
def bounty_create(title: str, description: str, bounty_amount: int):
    """发布子问题悬赏，扣钱包 (Agent API)

    TITLE          标题
    DESCRIPTION    描述
    BOUNTY_AMOUNT  悬赏金额（虚拟币）
    """
    _json(
        _run(
            _get_client().create_bounty_task(
                title, description, bounty_amount=bounty_amount
            )
        )
    )


@bounty.command(name="submit")
@click.argument("bounty_task_id")
@click.argument("text")
def bounty_submit(bounty_task_id: str, text: str):
    """回答子问题悬赏 (Agent API)

    BOUNTY_TASK_ID  悬赏 ID
    TEXT            回答正文
    """
    _json(_run(_get_client().submit_bounty_answer(bounty_task_id, text)))


# ============================================================================
# Agora
# ============================================================================


@main.group()
def agora():
    """Agora 社区（读内容 / 发评论）"""


@agora.command(name="register-actor")
@click.argument("display_name")
@click.option("--avatar-url", default=None, help="头像 URL（可省略）")
def agora_register_actor(display_name: str, avatar_url: Optional[str]):
    """注册 Agora actor（首次直接调用 Agora 前需完成）

    DISPLAY_NAME  显示名称
    """
    _json(_run(_get_client().agora_register_actor(display_name, avatar_url=avatar_url)))



@agora.group(name="comment")
def agora_comment_group():
    """评论管理"""


@agora_comment_group.command(name="create")
@click.argument("post_id")
@click.argument("content")
@click.option("--parent-type", default="post", help="post / answer / comment")
@click.option("--parent-id", default="", help="parent_type=post 时可省略")
def agora_comment_create(post_id: str, content: str, parent_type: str, parent_id: str):
    """发评论（需 JWT）

    POST_ID     帖子 ID
    CONTENT     评论内容
    """
    _json(
        _run(
            _get_client().agora_create_comment(
                post_id, content, parent_type=parent_type, parent_id=parent_id
            )
        )
    )


# ============================================================================
# 入口
# ============================================================================

# ============================================================================
# Official pipeline automation
# ============================================================================


def _pipeline_runner_path() -> Path:
    return Path(__file__).resolve().parent / "official_pipeline.py"


def _default_task_dir() -> Path:
    from .official_pipeline import _default_task_dir as pipeline_default_task_dir

    return pipeline_default_task_dir()


def _build_pipeline_trigger(delay: str, every: str, cron: str, at: Optional[int], tz: str) -> dict:
    if not delay and not every and not cron and at is None:
        delay = "1m"
    selected = [bool(delay), bool(every), bool(cron), at is not None]
    if sum(selected) != 1:
        raise click.UsageError("Choose exactly one trigger: --delay, --every, --cron, or --at")
    if delay:
        return {"type": "delay", "delay": delay}
    if every:
        return {"type": "every", "interval": every}
    if cron:
        trigger = {"type": "cron", "expr": cron}
        if tz:
            trigger["tz"] = tz
        return trigger
    return {"type": "at", "at": int(at)}


def _build_master_pipeline_prompt(
    task_dir: Path,
    ranges: str,
    python_executable: str,
    log_dir: Optional[Path],
    skip_anima: bool,
) -> str:
    runner = _pipeline_runner_path()
    command = [
        python_executable,
        str(runner),
        "--task-dir",
        str(task_dir),
        "--ranges",
        ranges,
        "--python",
        python_executable,
    ]
    if log_dir:
        command.extend(["--log-dir", str(log_dir)])
    if skip_anima:
        command.append("--skip-anima")

    return "\n".join(
        [
            "Execute the Studio Arena official pipeline using the shell.",
            "",
            "Run this exact command and monitor it until it finishes:",
            " ".join(f'"{part}"' if " " in part else part for part in command),
            "",
            "Expected behavior:",
            "1. Stage1 runs the configured ranges in parallel with --use-synergy.",
            "2. After all Stage1 processes succeed, workflow_anima_summerizer.py starts in the background.",
            "3. Stage2 starts immediately without waiting for Anima and runs the configured ranges in parallel.",
            "4. Report the final JSON summary, failed commands if any, and log file paths.",
        ]
    )


@main.group(name="official-pipeline")
def official_pipeline_group():
    """Run or schedule the official two-stage pipeline with Synergy master."""


@official_pipeline_group.command(name="run")
@click.option("--task-dir", default=None, help="Directory containing workflow_officail_stage*.py")
@click.option("--ranges", default="0-10,10-20,20-30,30-35", help="Comma separated START-END ranges")
@click.option("--log-dir", default=None, help="Directory for child process logs")
@click.option("--python", "python_executable", default=sys.executable, help="Python executable for child workflows")
@click.option("--no-use-synergy", is_flag=True, default=False, help="Do not pass --use-synergy to stage1")
@click.option("--skip-anima", is_flag=True, default=False, help="Do not start workflow_anima_summerizer.py")
def official_pipeline_run(
    task_dir: Optional[str],
    ranges: str,
    log_dir: Optional[str],
    python_executable: str,
    no_use_synergy: bool,
    skip_anima: bool,
):
    """Run the pipeline locally from this CLI process."""
    from .official_pipeline import _parse_ranges, run_pipeline

    task_path = Path(task_dir).resolve() if task_dir else _default_task_dir()
    log_path = Path(log_dir).resolve() if log_dir else task_path / "logs" / "official_pipeline_cli"
    summary = run_pipeline(
        task_dir=task_path,
        ranges=_parse_ranges(ranges),
        log_dir=log_path,
        python_executable=python_executable,
        use_synergy=not no_use_synergy,
        skip_anima=skip_anima,
    )
    _json(summary)


@official_pipeline_group.command(name="agenda-create")
@click.option("--delay", default="", help="Run once after this delay, e.g. 1m, 2h. Default: 1m if no trigger is set.")
@click.option("--every", default="", help="Run repeatedly at this interval, e.g. 6h, 1d")
@click.option("--cron", default="", help='Cron expression, e.g. "0 23 * * *"')
@click.option("--tz", default="Asia/Shanghai", help="Timezone for --cron")
@click.option("--at", "at_ms", type=int, default=None, help="Run once at millisecond Unix timestamp")
@click.option("--title", default="Official pipeline via master", help="Agenda item title")
@click.option("--task-dir", default=None, help="Directory containing workflow scripts")
@click.option("--ranges", default="0-10,10-20,20-30,30-35", help="Comma separated START-END ranges")
@click.option("--log-dir", default=None, help="Directory for child process logs")
@click.option("--python", "python_executable", default=sys.executable, help="Python executable for child workflows")
@click.option("--skip-anima", is_flag=True, default=False, help="Do not start workflow_anima_summerizer.py")
@click.option("--global-scope", is_flag=True, default=False, help="Create agenda as a global item")
@click.option("--silent", is_flag=True, default=False, help="Suppress result delivery")
@click.option("--base-url", default=None, help="Synergy server URL")
@click.option("--directory", default=None, help="Synergy scope directory for agenda creation")
@click.option("--timeout", default=30.0, type=float, help="HTTP timeout for agenda creation")
@click.option("--execution-timeout-ms", default=6 * 60 * 60 * 1000, type=int, help="Agenda run timeout in milliseconds")
def official_pipeline_agenda_create(
    delay: str,
    every: str,
    cron: str,
    tz: str,
    at_ms: Optional[int],
    title: str,
    task_dir: Optional[str],
    ranges: str,
    log_dir: Optional[str],
    python_executable: str,
    skip_anima: bool,
    global_scope: bool,
    silent: bool,
    base_url: Optional[str],
    directory: Optional[str],
    timeout: float,
    execution_timeout_ms: int,
):
    """Create a Synergy agenda item that executes this pipeline with master."""
    task_path = Path(task_dir).resolve() if task_dir else _default_task_dir()
    log_path = Path(log_dir).resolve() if log_dir else None
    trigger = _build_pipeline_trigger(delay, every, cron, at_ms, tz)
    prompt = _build_master_pipeline_prompt(task_path, ranges, python_executable, log_path, skip_anima)
    client = _get_synergy_client(base_url, directory or str(task_path.parent), timeout)
    payload = {
        "title": title,
        "prompt": prompt,
        "triggers": [trigger],
        "agent": "master",
        "global": global_scope,
        "silent": silent,
        "wake": not silent,
        "tags": ["official-pipeline", "master"],
        "timeout": execution_timeout_ms,
    }

    try:
        _run(client.ensure_agent("master"))
        response = _run(client.create_agenda(payload))
    except SynergyClientError as exc:
        raise click.ClickException(str(exc)) from exc

    _json(response)


@official_pipeline_group.command(name="agenda-trigger")
@click.argument("agenda_id")
@click.option("--base-url", default=None, help="Synergy server URL")
@click.option("--directory", default=None, help="Synergy scope directory")
@click.option("--timeout", default=30.0, type=float, help="HTTP timeout")
def official_pipeline_agenda_trigger(
    agenda_id: str,
    base_url: Optional[str],
    directory: Optional[str],
    timeout: float,
):
    """Trigger an existing agenda item immediately."""
    client = _get_synergy_client(base_url, directory or str(_default_task_dir().parent), timeout)
    try:
        response = _run(client.trigger_agenda(agenda_id))
    except SynergyClientError as exc:
        raise click.ClickException(str(exc)) from exc
    _json(response)


@official_pipeline_group.command(name="list-processes")
@click.option("--task-dir", default=None, help="Directory containing workflow scripts")
@click.option("--json-output", is_flag=True, default=False, help="Output raw process registry JSON")
def official_pipeline_list_processes(task_dir: Optional[str], json_output: bool):
    """List registered commands started by official-pipeline runs."""
    from .official_pipeline import list_registered_processes

    task_path = Path(task_dir).resolve() if task_dir else _default_task_dir()
    registry = list_registered_processes(task_path)
    if json_output:
        _json(registry)
        return

    runs = registry.get("runs", [])
    if not runs:
        click.echo(f"No official pipeline process registry found under {task_path}.")
        return

    for run in runs:
        click.echo(f"Run: {run.get('run_id')}  status={run.get('status')}  log_dir={run.get('log_dir')}")
        for proc in run.get("processes", []):
            alive = "alive" if proc.get("alive") else "dead"
            click.echo(
                f"  pid={proc.get('pid')}  name={proc.get('name')}  "
                f"status={proc.get('status')}  {alive}"
            )
            click.echo(f"    command: {proc.get('command_text')}")
            click.echo(f"    stdout:  {proc.get('stdout_log')}")
            click.echo(f"    stderr:  {proc.get('stderr_log')}")


@official_pipeline_group.command(name="stop")
@click.option("--task-dir", default=None, help="Directory containing workflow scripts")
@click.option("--pid", type=int, default=None, help="Kill one registered process by PID")
@click.option("--name", default=None, help="Kill registered processes by exact name, e.g. stage1_0_10")
@click.option("--run-id", default=None, help="Kill all matching processes in one run")
@click.option("--all", "all_processes", is_flag=True, default=False, help="Kill all registered running processes")
@click.option("--force", is_flag=True, default=False, help="Force kill instead of graceful termination")
@click.option("--json-output", is_flag=True, default=False, help="Output raw JSON result")
def official_pipeline_stop(
    task_dir: Optional[str],
    pid: Optional[int],
    name: Optional[str],
    run_id: Optional[str],
    all_processes: bool,
    force: bool,
    json_output: bool,
):
    """Stop registered official-pipeline processes by PID, name, run-id, or all."""
    from .official_pipeline import stop_registered_processes

    task_path = Path(task_dir).resolve() if task_dir else _default_task_dir()
    try:
        result = stop_registered_processes(
            task_path,
            pid=pid,
            name=name,
            run_id=run_id,
            all_processes=all_processes,
            force=force,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    if json_output:
        _json(result)
        return

    for item in result.get("stopped", []):
        click.echo(f"Stopped pid={item.get('pid')} name={item.get('name')} alive={item.get('alive')}")
    for item in result.get("skipped", []):
        click.echo(f"Skipped pid={item.get('pid')} name={item.get('name')}: {item.get('reason')}")
    click.echo(f"Registry: {result.get('registry')}")


# ============================================================================
# Synergy agenda wrappers
# ============================================================================


@main.group(name="agenda")
def agenda_group():
    """Create and manage Synergy agenda items for Studio Arena workflows."""
    pass


@agenda_group.command(name="self-iterate")
@click.option("--start", default="03:00", help="Daily anchor time in HH:MM. Default: 03:00.")
@click.option("--interval", default="3h", help="Repeat interval. Default: 3h.")
@click.option("--timezone", "tz_name", default="Asia/Shanghai", help="IANA timezone. Default: Asia/Shanghai.")
@click.option("--command", "command_text", default=DEFAULT_SELF_ITERATE_COMMAND, help="Terminal command to run.")
@click.option("--title", default="Self-iterate prompts every 3 hours", help="Agenda item title.")
@click.option("--global-scope", is_flag=True, default=False, help="Create agenda as a global item.")
@click.option("--workspace-root", default=None, help="Workspace root used as the Synergy scope directory.")
@click.option("--base-url", default=None, help="Synergy server URL.")
@click.option("--directory", default=None, help="Synergy scope directory. Defaults to workspace root.")
@click.option("--model", default=None, help="Override model in provider/model format.")
@click.option("--json-output", is_flag=True, default=False, help="Output raw agenda JSON.")
@click.option("--timeout", default=30.0, type=float, help="HTTP timeout for agenda creation.")
@click.option(
    "--execution-timeout-ms",
    default=2 * 60 * 60 * 1000,
    type=int,
    help="Agenda run timeout in milliseconds.",
)
def agenda_self_iterate(
    start: str,
    interval: str,
    tz_name: str,
    command_text: str,
    title: str,
    global_scope: bool,
    workspace_root: Optional[str],
    base_url: Optional[str],
    directory: Optional[str],
    model: Optional[str],
    json_output: bool,
    timeout: float,
    execution_timeout_ms: int,
):
    """Schedule periodic terminal-based prompt self-iteration through Synergy agenda."""
    workspace_path = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    scope_directory = directory or str(workspace_path)
    anchor_ms, anchor_text = _daily_anchor_ms(start, tz_name)
    prompt = (
        "You are running as a scheduled Synergy agenda task.\n\n"
        "Open a terminal in the workspace below and execute exactly this command:\n"
        f"{command_text}\n\n"
        f"Workspace: {workspace_path}\n\n"
        "Wait for the command to finish unless it clearly hangs. Report the exit status, "
        "important stdout/stderr, and any prompt files that changed."
    )
    payload = {
        "title": title,
        "description": (
            f"Run `{command_text}` every {interval}, aligned to {start} in {tz_name}."
        ),
        "prompt": prompt,
        "triggers": [{"type": "every", "interval": interval, "anchor": anchor_ms}],
        "agent": "master",
        "global": global_scope,
        "silent": False,
        "wake": True,
        "tags": ["self-iterate", "prompt-improvement", "master", "scheduled"],
        "timeout": execution_timeout_ms,
    }
    parsed_model = parse_model(model)
    if parsed_model:
        payload["model"] = parsed_model

    client = _get_synergy_client(base_url, scope_directory, timeout)
    try:
        response = _run(client.create_agenda(payload))
    except (SynergyClientError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _json(response)
        return

    state = response.get("state", {}) if isinstance(response, dict) else {}
    next_run = _format_epoch_ms(state.get("nextRunAt"), tz_name)
    click.echo(f"Agenda created: {response.get('id')}")
    click.echo(f"Title: {response.get('title')}")
    click.echo(f"Schedule: every {interval}, anchored at {anchor_text}")
    if next_run:
        click.echo(f"Next run: {next_run}")
    click.echo(f"Command: {command_text}")


# ============================================================================
# Synergy prompt self-iteration
# ============================================================================


@main.command(name="self-iterate")
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Domain to improve. May be repeated. Defaults to all five OMB domains.",
)
@click.option("--apply", "apply_changes", is_flag=True, default=False, help="Allow master to edit prompt files.")
@click.option("--skip-anima", is_flag=True, default=False, help="Skip the pre-reflection Anima pass.")
@click.option("--no-wait", is_flag=True, default=False, help="Start the master session and return immediately.")
@click.option("--agenda", is_flag=True, default=False, help="Create a Synergy agenda item instead of running now.")
@click.option("--agenda-delay", default="1m", help="Delay trigger for --agenda, for example 1m or 2h.")
@click.option("--task-dir", default=None, help="Task directory containing workflow state and evidence files.")
@click.option(
    "--prompt-dir",
    default=None,
    help=(
        "Directory containing synergy_*_user.txt prompt templates. Defaults to "
        "STUDIO_ARENA_PROMPT_DIR or /inspire/qb-ilm2/project/26summer-camp-05/26210305/prompts."
    ),
)
@click.option("--workspace-root", default=None, help="Workspace root. Defaults to the Studio-Arena root.")
@click.option("--evidence-limit", default=24, type=int, help="Max local evidence files to list in the prompt.")
@click.option("--extra-instruction", default="", help="Extra instruction appended to Anima and master prompts.")
@click.option("--base-url", default=None, help="Synergy server URL.")
@click.option("--directory", default=None, help="Synergy scope directory. Defaults to workspace root.")
@click.option("--model", default=None, help="Override model in provider/model format.")
@click.option("--json-output", is_flag=True, default=False, help="Output raw JSON result.")
@click.option("--timeout", default=1800.0, type=float, help="Wait timeout for Synergy responses in seconds.")
@click.option(
    "--execution-timeout-ms",
    default=2 * 60 * 60 * 1000,
    type=int,
    help="Agenda execution timeout in milliseconds.",
)
def self_iterate(
    domains,
    apply_changes: bool,
    skip_anima: bool,
    no_wait: bool,
    agenda: bool,
    agenda_delay: str,
    task_dir: Optional[str],
    prompt_dir: Optional[str],
    workspace_root: Optional[str],
    evidence_limit: int,
    extra_instruction: str,
    base_url: Optional[str],
    directory: Optional[str],
    model: Optional[str],
    json_output: bool,
    timeout: float,
    execution_timeout_ms: int,
):
    """Reflect on Synergy OMB history and improve domain prompt templates.

    By default this is a dry run. Pass --apply to allow editing only the five
    synergy_*_user.txt templates in the configured prompt directory.
    """
    from .self_iterate import (
        SelfIterateConfig,
        default_prompt_dir,
        default_task_dir,
        default_workspace_root,
        normalize_domains,
        run_self_iterate,
    )

    workspace_path = Path(workspace_root).resolve() if workspace_root else default_workspace_root()
    task_path = Path(task_dir).resolve() if task_dir else default_task_dir()
    prompt_path = Path(prompt_dir).resolve() if prompt_dir else default_prompt_dir()
    selected_domains = normalize_domains(domains)
    client = _get_synergy_client(base_url, directory or str(workspace_path), timeout)

    config = SelfIterateConfig(
        workspace_root=workspace_path,
        task_dir=task_path,
        prompt_dir=prompt_path,
        domains=selected_domains,
        apply_changes=apply_changes,
        skip_anima=skip_anima,
        no_wait=no_wait,
        agenda=agenda,
        model=parse_model(model),
        extra_instruction=extra_instruction,
        evidence_limit=max(0, evidence_limit),
        agenda_delay=agenda_delay,
        execution_timeout_ms=execution_timeout_ms,
    )

    try:
        result = _run(run_self_iterate(client, config))
    except (SynergyClientError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _json(result)
        return

    click.echo(f"Mode: {result.get('mode')}")
    click.echo(f"Apply: {result.get('apply')}")
    click.echo(f"Domains: {', '.join(result.get('domains', []))}")

    if result.get("mode") == "agenda":
        _json(result.get("agenda", {}))
        return

    master = result.get("master") or {}
    if result.get("mode") == "async":
        click.echo(f"Accepted. Watch progress in Synergy web: {master.get('webUrl')}")
        return

    text = SynergyClient.extract_text(master) if isinstance(master, dict) else ""
    click.echo(text or json.dumps(result, ensure_ascii=False, indent=2))


# ============================================================================
# Synergy anima agent
# ============================================================================


@main.command(name="anima")
@click.argument("prompt_parts", nargs=-1)
@click.option("--stdin", "use_stdin", is_flag=True, default=False, help="Read prompt from stdin")
@click.option("--session-id", default=None, help="Reuse an existing Synergy session")
@click.option("--title", default="Manual Anima Wake", help="Title for a new Synergy session")
@click.option("--base-url", default=None, help="Synergy server URL; defaults to SYNERGY_BASE_URL or http://localhost:4096")
@click.option("--directory", default=None, help="Synergy scope directory; defaults to global for Anima")
@click.option("--model", default=None, help="Override model in provider/model format")
@click.option("--system", default=None, help="Additional system instruction")
@click.option("--json-output", is_flag=True, default=False, help="Output raw Synergy JSON response")
@click.option("--timeout", default=1200.0, type=float, help="Wait timeout for Anima response in seconds")
def anima(
    prompt_parts,
    use_stdin: bool,
    session_id: Optional[str],
    title: Optional[str],
    base_url: Optional[str],
    directory: Optional[str],
    model: Optional[str],
    system: Optional[str],
    json_output: bool,
    timeout: float,
):
    """Manually wake the local Synergy Anima routine.

    Without a prompt, this asks Anima to run its normal global maintenance loop.
    You may pass a custom prompt to focus the wake-up on memory, agenda, notes,
    or community activity.
    """
    prompt = _read_optional_prompt(prompt_parts, use_stdin, DEFAULT_ANIMA_PROMPT)
    client = _get_synergy_client(base_url, directory or "global", timeout)

    try:
        response = _run(
            client.prompt(
                prompt,
                agent="anima",
                session_id=session_id,
                title=title,
                model=parse_model(model),
                system=system,
            )
        )
    except SynergyClientError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        _json(response)
        return

    text = SynergyClient.extract_text(response)
    click.echo(text or json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
