"""Prompt self-improvement orchestration for the Studio Arena Synergy workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional, Sequence

if TYPE_CHECKING:
    from .synergy import SynergyClient


DEFAULT_PROMPT_DIR = Path(
    os.environ.get(
        "STUDIO_ARENA_PROMPT_DIR",
        "/inspire/qb-ilm2/project/26summer-camp-05/26210305/prompts",
    )
)


@dataclass(frozen=True)
class DomainSpec:
    domain: str
    agent: str
    prompt_file: str


DOMAIN_SPECS: dict[str, DomainSpec] = {
    "Finance": DomainSpec("Finance", "omb-finance", "synergy_finance_user.txt"),
    "Law": DomainSpec("Law", "omb-law", "synergy_law_user.txt"),
    "Healthcare": DomainSpec("Healthcare", "omb-healthcare", "synergy_healthcare_user.txt"),
    "Natural Science": DomainSpec("Natural Science", "omb-natural-science", "synergy_natural_science_user.txt"),
    "Industry": DomainSpec("Industry", "omb-industry", "synergy_industry_user.txt"),
}


@dataclass(frozen=True)
class SelfIterateConfig:
    workspace_root: Path
    task_dir: Path
    prompt_dir: Path
    domains: tuple[str, ...]
    apply_changes: bool
    skip_anima: bool
    no_wait: bool
    agenda: bool
    model: Optional[dict[str, str]] = None
    extra_instruction: str = ""
    evidence_limit: int = 24
    agenda_delay: str = "1m"
    execution_timeout_ms: int = 2 * 60 * 60 * 1000


def default_workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_prompt_dir() -> Path:
    return DEFAULT_PROMPT_DIR


def default_task_dir() -> Path:
    return default_prompt_dir().parent


def normalize_domains(values: Iterable[str]) -> tuple[str, ...]:
    aliases = {
        "finance": "Finance",
        "law": "Law",
        "healthcare": "Healthcare",
        "health": "Healthcare",
        "medical": "Healthcare",
        "natural-science": "Natural Science",
        "natural_science": "Natural Science",
        "natural science": "Natural Science",
        "science": "Natural Science",
        "industry": "Industry",
        "industrial": "Industry",
    }
    result: list[str] = []
    for value in values:
        key = value.strip()
        domain = DOMAIN_SPECS.get(key)
        if not domain:
            domain_name = aliases.get(key.lower())
            domain = DOMAIN_SPECS.get(domain_name or "")
        if not domain:
            valid = ", ".join(DOMAIN_SPECS)
            raise ValueError(f"Unknown domain {value!r}. Valid domains: {valid}")
        if domain.domain not in result:
            result.append(domain.domain)
    return tuple(result or DOMAIN_SPECS.keys())


def validate_layout(config: SelfIterateConfig) -> None:
    if not config.workspace_root.exists():
        raise FileNotFoundError(f"Workspace root not found: {config.workspace_root}")
    if not config.task_dir.exists():
        raise FileNotFoundError(f"Task directory not found: {config.task_dir}")
    if not config.prompt_dir.exists():
        raise FileNotFoundError(f"Prompt directory not found: {config.prompt_dir}")

    missing: list[str] = []
    for domain in config.domains:
        spec = DOMAIN_SPECS[domain]
        prompt_path = config.prompt_dir / spec.prompt_file
        agent_path = config.workspace_root / ".synergy" / "agent" / f"{spec.agent}.md"
        if not prompt_path.exists():
            missing.append(str(prompt_path))
        if not agent_path.exists():
            missing.append(str(agent_path))

    if missing:
        raise FileNotFoundError("Required self-iteration files are missing:\n" + "\n".join(missing))


def target_prompt_paths(config: SelfIterateConfig) -> list[Path]:
    return [config.prompt_dir / DOMAIN_SPECS[domain].prompt_file for domain in config.domains]


def _read_text(path: Path, max_chars: int = 12000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]..."


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _collect_by_patterns(task_dir: Path, patterns: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in task_dir.glob(pattern) if path.is_file())
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)


def collect_evidence_inventory(config: SelfIterateConfig) -> list[str]:
    patterns = [
        "official*.json",
        "official_output*.json",
        "workflow_*state*.json",
        "output.json",
        "logs/official_pipeline_active.json",
    ]
    files = _collect_by_patterns(config.task_dir, patterns)

    log_dir = config.task_dir / "logs"
    if log_dir.exists():
        logs = sorted(log_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        files.extend(logs[: max(0, config.evidence_limit // 2)])

    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[: config.evidence_limit]
    return [_relative(path, config.workspace_root) for path in files]


def build_anima_prompt(config: SelfIterateConfig) -> str:
    domain_lines = "\n".join(f"- {domain}: {DOMAIN_SPECS[domain].agent}" for domain in config.domains)
    target_lines = "\n".join(f"- {path}" for path in target_prompt_paths(config))
    extra = ""
    if config.extra_instruction.strip():
        extra = f"\n\nAdditional user instruction:\n{config.extra_instruction.strip()}"

    return f"""Manual Anima wake-up for Synergy prompt self-improvement preparation.

This is a reflection-only preparation step. Do not edit files in this Anima run.

Scope:
- Workspace root: {config.workspace_root}
- Task directory: {config.task_dir}
- Prompt directory: {config.prompt_dir}
- Domains:
{domain_lines}
- Target prompt templates:
{target_lines}

Goal:
Prepare compact, evidence-backed guidance for improving the listed OneMillion-Bench Synergy domain prompt templates.

Please inspect your own long-term context:
1. Search memories for OneMillion-Bench, OMB, benchmark failure modes, domain agent names, prompt quality, feedback, stage1, and stage2.
2. Search recent sessions, notes, agenda logs, and domain-agent conversations related to the listed domains.
3. Identify reusable lessons about answer quality, factuality, reasoning, instruction following, language control, and formatting.
4. Distinguish durable lessons from one-off task details.
5. Do not write or edit the prompt files. You may update memory or notes only if you find a clearly durable lesson that is not already stored.

Return a concise domain-by-domain report with:
- evidence consulted
- repeated failure modes
- prompt improvements that are justified by the evidence
- things that should not be changed because evidence is weak
{extra}
"""


def _format_current_prompts(config: SelfIterateConfig) -> str:
    sections: list[str] = []
    for domain in config.domains:
        spec = DOMAIN_SPECS[domain]
        path = config.prompt_dir / spec.prompt_file
        sections.append(
            "\n".join(
                [
                    f"## {domain} ({spec.agent})",
                    f"Path: {path}",
                    "```text",
                    _read_text(path),
                    "```",
                ]
            )
        )
    return "\n\n".join(sections)


def _format_agent_files(config: SelfIterateConfig) -> str:
    sections: list[str] = []
    for domain in config.domains:
        spec = DOMAIN_SPECS[domain]
        path = config.workspace_root / ".synergy" / "agent" / f"{spec.agent}.md"
        sections.append(
            "\n".join(
                [
                    f"## {domain} agent file",
                    f"Path: {path}",
                    "```markdown",
                    _read_text(path, max_chars=6000),
                    "```",
                ]
            )
        )
    return "\n\n".join(sections)


def build_master_prompt(config: SelfIterateConfig, anima_reflection: str = "") -> str:
    action = "APPLY MODE: you may edit only the listed target prompt template files." if config.apply_changes else (
        "DRY-RUN MODE: do not edit or write any files. Produce a proposed patch and rationale only."
    )
    allowed_paths = "\n".join(f"- {path}" for path in target_prompt_paths(config))
    domain_lines = "\n".join(
        f"- {domain}: agent={DOMAIN_SPECS[domain].agent}, prompt={DOMAIN_SPECS[domain].prompt_file}"
        for domain in config.domains
    )
    evidence = collect_evidence_inventory(config)
    evidence_lines = "\n".join(f"- {item}" for item in evidence) if evidence else "- No local evidence files found."
    anima_block = ""
    if anima_reflection.strip():
        anima_block = f"""
<anima_reflection>
{anima_reflection.strip()}
</anima_reflection>
"""
    extra = ""
    if config.extra_instruction.strip():
        extra = f"\nAdditional user instruction:\n{config.extra_instruction.strip()}\n"

    return f"""You are Synergy master running a controlled prompt self-improvement pass.

{action}

Hard constraints:
- Do not modify anything under this Synergy source tree: {config.workspace_root / "synergy"}
- Do not modify StudioArenaCLI code.
- Do not modify .synergy/agent files in this pass.
- The only files you may edit in APPLY MODE are:
{allowed_paths}
- Preserve all existing placeholders such as {{stage}}, {{title}}, {{tags_text}}, {{description}}, {{answer_language}}, {{search_context}}, {{previous_answer_block}}, and {{feedback_block}}.
- Preserve the exact final-answer contract requiring <FINAL_ANSWER>...</FINAL_ANSWER>.
- Keep prompt changes concise, domain-specific, and evidence-backed. Avoid turning prompts into long policy documents.
- If evidence is weak for a domain, leave that domain unchanged and say why.

Domains in scope:
{domain_lines}

Workspace:
- Root: {config.workspace_root}
- Task directory: {config.task_dir}
- Prompt directory: {config.prompt_dir}

Local evidence inventory you should inspect when useful:
{evidence_lines}

Current target prompt templates:
{_format_current_prompts(config)}

Current domain agent definitions for context only; do not edit these:
{_format_agent_files(config)}
{anima_block}
{extra}
Required self-iteration procedure:
1. Use Synergy's own memory and history tools before deciding changes:
   - memory_search / memory_get for OneMillion-Bench, OMB, each domain, each domain agent, benchmark feedback, failure modes, prompt issues.
   - note_search / note_read for prior summaries.
   - session_search / session_list / session_read for recent OMB answer sessions and feedback loops.
   - agenda_logs if relevant.
2. Inspect local workflow evidence files when available, especially stage state JSON and logs that contain prior answers, comments, feedback, or failure traces.
3. For each domain, judge whether the current prompt caused or failed to prevent repeated issues.
4. If APPLY MODE, edit only the affected listed prompt files. Prefer small targeted insertions in the "Domain operating principles" or "Execution policy" sections.
5. After any edit, read the changed file and verify placeholders and final-answer wrapper survived.
6. Report:
   - evidence consulted
   - domains changed / unchanged
   - exact files edited
   - summary of prompt improvements
   - residual risks or missing evidence
"""


async def _ensure_agents(client: SynergyClient, config: SelfIterateConfig) -> None:
    required = ["master", *(DOMAIN_SPECS[domain].agent for domain in config.domains)]
    if not config.skip_anima and not config.no_wait and not config.agenda:
        required.append("anima")
    for agent in dict.fromkeys(required):
        await client.ensure_agent(agent)


async def run_self_iterate(client: SynergyClient, config: SelfIterateConfig) -> dict[str, Any]:
    from .synergy import SynergyClient

    validate_layout(config)
    await _ensure_agents(client, config)

    anima_response: dict[str, Any] | None = None
    anima_text = ""
    if not config.skip_anima and not config.no_wait and not config.agenda:
        anima_response = await client.prompt(
            build_anima_prompt(config),
            agent="anima",
            title="Self-Iterate Anima Reflection",
            model=config.model,
        )
        anima_text = SynergyClient.extract_text(anima_response)

    master_prompt = build_master_prompt(config, anima_text)
    title = "Self-Iterate OMB Domain Prompts"

    if config.agenda:
        payload = {
            "title": title,
            "prompt": master_prompt,
            "triggers": [{"type": "delay", "delay": config.agenda_delay}],
            "agent": "master",
            "global": False,
            "silent": False,
            "wake": True,
            "tags": ["self-iterate", "prompt-improvement", "master"],
            "timeout": config.execution_timeout_ms,
        }
        response = await client.create_agenda(payload)
        return {
            "mode": "agenda",
            "apply": config.apply_changes,
            "domains": list(config.domains),
            "agenda": response,
        }

    if config.no_wait:
        response = await client.prompt_async(
            master_prompt,
            agent="master",
            title=title,
            model=config.model,
        )
        return {
            "mode": "async",
            "apply": config.apply_changes,
            "domains": list(config.domains),
            "master": response,
        }

    master_response = await client.prompt(
        master_prompt,
        agent="master",
        title=title,
        model=config.model,
    )
    return {
        "mode": "sync",
        "apply": config.apply_changes,
        "domains": list(config.domains),
        "anima": anima_response,
        "master": master_response,
    }
