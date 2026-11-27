# find_reads on the 0.5 measured run: grouped counts (report-0.5.0.md, disclosure 10)

Input: the run's raw streams, 1,160 stream.jsonl files (22,992 lines, none unparseable), kept off git [run record];
7,170 tool calls in all.
The reviewer's find_reads.py as written: 0 hits (it reads no tool call: the runner wraps each event as {"ts", "event"}).
find_reads_envelope.py (this folder): 5,345 hits.
Tool calls naming /opt/memkernel, oracles, task.json or reference/, any arm: 0 of 7,170.

## find_reads hits by arm, and by first-matching part of the pattern

hits by arm: {'fs_grep': 1118, 'placebo': 921, 'protocol': 906, 'bare': 866, 'claude_md': 831, 'memkernel': 665, 'wiki_studio': 38}
first-matching token: {'/runs/': 5337, '..': 7, '~': 1}

hits by arm and task:
  bare         lc-compact-alert-threshold               55
  bare         lc-compact-name-order                    58
  bare         lc-compact-page-size                     56
  bare         lc-compact-port                          59
  bare         lc-compact-text-encoding                 55
  bare         lc-retain-order-ids                      36
  bare         lc-retain-retry-revised                  66
  bare         lc-retain-rounding                       35
  bare         lc-retain-separator-revised              47
  bare         lc-retain-utc-stamps                     42
  bare         lc-reval-identity-casefold               37
  bare         lc-reval-log-masking                     40
  bare         lc-reval-manifest-paths                  33
  bare         lc-reval-rounding-moved                  35
  bare         lc-reval-timeout-units                   34
  bare         lc-wiki-backoff                          38
  bare         lc-wiki-feature-flags                    33
  bare         lc-wiki-minor-units                      36
  bare         lc-wiki-release-tags                     31
  bare         lc-wiki-slugs                            40
  claude_md    lc-compact-alert-threshold               55
  claude_md    lc-compact-name-order                    59
  claude_md    lc-compact-page-size                     59
  claude_md    lc-compact-port                          60
  claude_md    lc-compact-text-encoding                 54
  claude_md    lc-retain-order-ids                      34
  claude_md    lc-retain-retry-revised                  52
  claude_md    lc-retain-rounding                       17
  claude_md    lc-retain-separator-revised              52
  claude_md    lc-retain-utc-stamps                     45
  claude_md    lc-reval-identity-casefold               27
  claude_md    lc-reval-log-masking                     32
  claude_md    lc-reval-manifest-paths                  28
  claude_md    lc-reval-rounding-moved                  28
  claude_md    lc-reval-timeout-units                   41
  claude_md    lc-wiki-backoff                          44
  claude_md    lc-wiki-feature-flags                    39
  claude_md    lc-wiki-minor-units                      34
  claude_md    lc-wiki-release-tags                     32
  claude_md    lc-wiki-slugs                            39
  fs_grep      lc-compact-alert-threshold               61
  fs_grep      lc-compact-name-order                    61
  fs_grep      lc-compact-page-size                     64
  fs_grep      lc-compact-port                          62
  fs_grep      lc-compact-text-encoding                 56
  fs_grep      lc-retain-order-ids                      43
  fs_grep      lc-retain-retry-revised                  81
  fs_grep      lc-retain-rounding                       52
  fs_grep      lc-retain-separator-revised              80
  fs_grep      lc-retain-utc-stamps                     46
  fs_grep      lc-reval-identity-casefold               51
  fs_grep      lc-reval-log-masking                     51
  fs_grep      lc-reval-manifest-paths                  49
  fs_grep      lc-reval-rounding-moved                  49
  fs_grep      lc-reval-timeout-units                   51
  fs_grep      lc-wiki-backoff                          47
  fs_grep      lc-wiki-feature-flags                    55
  fs_grep      lc-wiki-minor-units                      60
  fs_grep      lc-wiki-release-tags                     47
  fs_grep      lc-wiki-slugs                            52
  memkernel    lc-compact-alert-threshold               53
  memkernel    lc-compact-name-order                    45
  memkernel    lc-compact-page-size                     48
  memkernel    lc-compact-port                          45
  memkernel    lc-compact-text-encoding                 47
  memkernel    lc-retain-order-ids                      18
  memkernel    lc-retain-retry-revised                  28
  memkernel    lc-retain-rounding                       16
  memkernel    lc-retain-separator-revised              29
  memkernel    lc-retain-utc-stamps                     20
  memkernel    lc-reval-identity-casefold               23
  memkernel    lc-reval-log-masking                     23
  memkernel    lc-reval-manifest-paths                  22
  memkernel    lc-reval-rounding-moved                  18
  memkernel    lc-reval-timeout-units                   27
  memkernel    lc-wiki-backoff                          42
  memkernel    lc-wiki-feature-flags                    39
  memkernel    lc-wiki-minor-units                      44
  memkernel    lc-wiki-release-tags                     37
  memkernel    lc-wiki-slugs                            41
  placebo      lc-compact-alert-threshold               63
  placebo      lc-compact-name-order                    61
  placebo      lc-compact-page-size                     60
  placebo      lc-compact-port                          60
  placebo      lc-compact-text-encoding                 57
  placebo      lc-retain-order-ids                      39
  placebo      lc-retain-retry-revised                  67
  placebo      lc-retain-rounding                       33
  placebo      lc-retain-separator-revised              57
  placebo      lc-retain-utc-stamps                     43
  placebo      lc-reval-identity-casefold               42
  placebo      lc-reval-log-masking                     41
  placebo      lc-reval-manifest-paths                  34
  placebo      lc-reval-rounding-moved                  40
  placebo      lc-reval-timeout-units                   34
  placebo      lc-wiki-backoff                          41
  placebo      lc-wiki-feature-flags                    37
  placebo      lc-wiki-minor-units                      35
  placebo      lc-wiki-release-tags                     38
  placebo      lc-wiki-slugs                            39
  protocol     lc-compact-alert-threshold               59
  protocol     lc-compact-name-order                    59
  protocol     lc-compact-page-size                     61
  protocol     lc-compact-port                          60
  protocol     lc-compact-text-encoding                 55
  protocol     lc-retain-order-ids                      38
  protocol     lc-retain-retry-revised                  66
  protocol     lc-retain-rounding                       40
  protocol     lc-retain-separator-revised              52
  protocol     lc-retain-utc-stamps                     41
  protocol     lc-reval-identity-casefold               38
  protocol     lc-reval-log-masking                     43
  protocol     lc-reval-manifest-paths                  35
  protocol     lc-reval-rounding-moved                  35
  protocol     lc-reval-timeout-units                   37
  protocol     lc-wiki-backoff                          37
  protocol     lc-wiki-feature-flags                    39
  protocol     lc-wiki-minor-units                      34
  protocol     lc-wiki-release-tags                     38
  protocol     lc-wiki-slugs                            39
  wiki_studio  lc-wiki-backoff                          5
  wiki_studio  lc-wiki-feature-flags                    2
  wiki_studio  lc-wiki-minor-units                      7
  wiki_studio  lc-wiki-release-tags                     15
  wiki_studio  lc-wiki-slugs                            9

## Tool calls naming a /runs/ path outside the session's own workspace: 1,233

own config = the session's own Claude Code config folder (s<N>/config, where Claude Code keeps its automatic memory); chain memory = fs_grep's rendered transcripts of earlier sessions (its designed channel); chain dir = the whole chain folder; own session dir = the session's folder outside workspace/ and config/; other chain = a path naming another chain (both memkernel calls failed: the file did not exist); run root = the run's top folder.

| Arm | own config | chain memory | chain dir | own session dir | other chain | run root |
|---|---|---|---|---|---|---|
| bare | 201 | 0 | 0 | 3 | 0 | 0 |
| claude_md | 143 | 0 | 0 | 0 | 0 | 0 |
| fs_grep | 144 | 227 | 48 | 1 | 0 | 0 |
| memkernel | 18 | 0 | 0 | 0 | 2 | 0 |
| placebo | 213 | 0 | 0 | 0 | 1 | 1 |
| protocol | 228 | 0 | 0 | 3 | 0 | 0 |
| wiki_studio | 0 | 0 | 0 | 0 | 0 | 0 |

## fs_grep: calls whose result listed files of an earlier session of the same chain

Judged by file paths at the start of the result's lines (Grep and Glob output). What each reached: stream.jsonl (the earlier session's raw stream) 22, config 20, instruction.md 15, workspace 10.

calls: 22
reached: {'config': 20, 'instruction.md': 15, 'stream.jsonl': 22, 'workspace': 10}
by task: {'lc-retain-order-ids': 1, 'lc-retain-retry-revised': 1, 'lc-retain-rounding': 4, 'lc-retain-separator-revised': 1, 'lc-retain-utc-stamps': 8, 'lc-reval-identity-casefold': 2, 'lc-reval-log-masking': 1, 'lc-reval-timeout-units': 4}
sessions: 18 chains: 18

- ('lc-retain-order-ids.fs_grep.r2/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "order.?id", "path": "/runs/measured-20261027T002737Z/lc-retain-order-ids.fs_grep.r2", "-i": true, "output_mode": "content", "head_limit": 50}')
- ('lc-retain-retry-revised.fs_grep.r2/s2', 'Grep', ['config', 'stream.jsonl'], '{"pattern": "attempt|retr", "path": "/runs/measured-20261027T002737Z/lc-retain-retry-revised.fs_grep.r2", "-i": true, "output_mode": "content", "head_limit": 50')
- ('lc-retain-rounding.fs_grep.r0/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "round|ROUND|quantize", "path": "/runs/measured-20261027T002737Z/lc-retain-rounding.fs_grep.r0", "output_mode": "content", "head_limit": 50}')
- ('lc-retain-rounding.fs_grep.r1/s1', 'Grep', ['config', 'stream.jsonl'], '{"pattern": "round|quantize|ROUND", "path": "/runs/measured-20261027T002737Z/lc-retain-rounding.fs_grep.r1", "-i": true, "output_mode": "content"}')
- ('lc-retain-rounding.fs_grep.r2/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-retain-rounding.fs_grep.r2"}')
- ('lc-retain-rounding.fs_grep.r3/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-retain-rounding.fs_grep.r3"}')
- ('lc-retain-separator-revised.fs_grep.r4/s1', 'Grep', ['config', 'stream.jsonl', 'workspace'], '{"pattern": "sep_default", "path": "/runs/measured-20261027T002737Z/lc-retain-separator-revised.fs_grep.r4", "output_mode": "content"}')
- ('lc-retain-utc-stamps.fs_grep.r0/s1', 'Grep', ['stream.jsonl'], '{"pattern": "stamp|strftime|isoformat|utc", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r0", "-i": true, "output_mode": "content"}')
- ('lc-retain-utc-stamps.fs_grep.r1/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "stamp|timestamp|strftime|isoformat", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r1", "output_mode": "content", "head_lim')
- ('lc-retain-utc-stamps.fs_grep.r1/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r1"}')
- ('lc-retain-utc-stamps.fs_grep.r2/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "stamp|strftime|isoformat|timestamp", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r2", "-i": true, "output_mode": "content')
- ('lc-retain-utc-stamps.fs_grep.r2/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r2"}')
- ('lc-retain-utc-stamps.fs_grep.r3/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "stamp|timestamp|strftime|isoformat", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r3", "output_mode": "content", "head_lim')
- ('lc-retain-utc-stamps.fs_grep.r4/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "stamp|strftime|isoformat|timestamp", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r4", "-i": true, "output_mode": "content')
- ('lc-retain-utc-stamps.fs_grep.r4/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-retain-utc-stamps.fs_grep.r4"}')
- ('lc-reval-identity-casefold.fs_grep.r1/s1', 'Grep', ['stream.jsonl'], '{"pattern": "identity|same_user|casefold|lower\\\\(", "path": "/runs/measured-20261027T002737Z/lc-reval-identity-casefold.fs_grep.r1", "-i": true, "output_mode": ')
- ('lc-reval-identity-casefold.fs_grep.r4/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-reval-identity-casefold.fs_grep.r4"}')
- ('lc-reval-log-masking.fs_grep.r3/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "log|mask|redact", "path": "/runs/measured-20261027T002737Z/lc-reval-log-masking.fs_grep.r3", "-i": true, "output_mode": "files_with_matches"}')
- ('lc-reval-timeout-units.fs_grep.r2/s1', 'Grep', ['config', 'instruction.md', 'stream.jsonl'], '{"pattern": "timeout", "path": "/runs/measured-20261027T002737Z/lc-reval-timeout-units.fs_grep.r2", "-i": true, "output_mode": "content", "head_limit": 50}')
- ('lc-reval-timeout-units.fs_grep.r3/s1', 'Grep', ['config', 'stream.jsonl'], '{"pattern": "timeout", "path": "/runs/measured-20261027T002737Z/lc-reval-timeout-units.fs_grep.r3", "-i": true, "output_mode": "content", "head_limit": 50}')
- ('lc-reval-timeout-units.fs_grep.r3/s1', 'Glob', ['config', 'instruction.md', 'stream.jsonl', 'workspace'], '{"pattern": "**/*", "path": "/runs/measured-20261027T002737Z/lc-reval-timeout-units.fs_grep.r3"}')
- ('lc-reval-timeout-units.fs_grep.r4/s1', 'Grep', ['config', 'stream.jsonl', 'workspace'], '{"pattern": "timeout", "path": "/runs/measured-20261027T002737Z/lc-reval-timeout-units.fs_grep.r4", "-i": true, "output_mode": "content", "head_limit": 50}')
