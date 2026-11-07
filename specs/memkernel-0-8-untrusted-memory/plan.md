---
feature_id: memkernel-0-8-untrusted-memory
spec_mode: full
status: draft
date: 2026-11-06
collaboration_mode: single
origin:
  issue: gosha70/memkernel#85
  urls:
    - https://github.com/gosha70/memkernel/issues/85
    - https://code.claude.com/docs/en/permissions
    - https://code.claude.com/docs/en/settings
  transcripts:
    - specs/memkernel-0-8-untrusted-memory/origin/2026-11-06-issue-85.md
  origin_claim: |
    #85: "Injected memory is untrusted text: present it as data, and ship a recommended Claude Code permissions
    example." Mark the checkpoint and context the SessionStart hook injects as data, inside a delimited block with
    one line saying they are stored notes, not instructions, within the 9,000-character budget and keeping the
    headings; ship a permissions example in templates/ with README text. The owner (2026-11-06): "Then the #85
    spec."
---

# Plan: injected memory as data, and a recommended permissions example (#85)

See `spec.md` for the decisions (recommendations for the owner), requirements and success criteria, and
`tasks.md` for the build. Spec mode `full`: it changes what every session-start block looks like (the hooks'
stdout contract) and adds a shipped template.
