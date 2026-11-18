# User stories

User stories are the north star of every feature's design: what each actor can do, and where each story stands. Each feature has one stories file here, named after its plan in `docs/plans/`, and the plan links to it rather than copying it. The rules are in `agents.md`, section 6.1.

The first stories file, Organizations, was written on 2026-11-15, after that feature was built. It is also the template for every future stories file.

## Missing tests show in red

In every stories file's "Tests passing" column, a story with no tests of a kind shows `0/0` for that kind in red: `0/0 (BU)` for a story with no unit test, `0/0 (BI)` for one with no integration test. Red is used for those `0/0` counts only. Set by the human maintainer on 2026-11-18.

Keep doing this even when every story has all its tests and no red shows, as in Organizations since 2026-11-18. The rule is for the next story that's missing a test, so the gap is spotted at a glance. The red is written as an HTML span, which shows in VS Code's Markdown preview (GitHub drops the colour):

```html
<span style="color:#c00000"><b>0/0 (BI)</b></span>
```

## Feature codes

Every story ID starts with its feature's code, so IDs stay unique across features (`ORG.D2.US.J3.A2`). Pick a new feature's code from letters not listed here, and add it when its stories file is created. A code never changes.

- `ORG`: Organizations (multi-tenancy). Stories: [`9-organizations-user-stories.md`](9-organizations-user-stories.md). Plan: [`9-organizations.md`](../9-organizations.md).
