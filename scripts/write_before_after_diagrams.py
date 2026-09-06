# ruff: noqa: E501

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"

DIAGRAMS = {
"01-dispatch-lifecycle": {
"before": r'''flowchart LR
    subgraph MAIN["Main session"]
        A["orch_dispatch tool call"]
        T["Receives compact session report"]
    end
    subgraph HOST["Host adapter"]
        B["Adapter starts dispatch"]
        W1["_await-run watcher<br/>progress only"]
        W2["_await-session-report watcher<br/>auto-return delivery"]
    end
    subgraph CORE["Core + scheduler"]
        C["orchestra do --json"]
        D{"Concurrency ok?"}
        H["Detached supervisor"]
        N["Finalize run"]
        R["Build consolidated report"]
    end
    subgraph DB["SQLite"]
        E[("runs row<br/>queued/running")]
        O[("terminal row<br/>summary + full result_output")]
    end
    subgraph FILES["Files"]
        F["state/requests/run-id.json"]
        G["logs/run-id.jsonl"]
    end
    subgraph SUB["Subagent"]
        J["child harness process"]
        L{"exits"}
    end
    A --> B --> C --> D
    D -- yes --> E --> H --> J --> L --> N --> O
    C --> F
    E --> G
    B -. starts .-> W1
    B -. starts .-> W2
    W1 -. polls .-> O
    W2 -. waits .-> R
    O --> R --> T
    style O fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    subgraph MAIN["Main session"]
        A["Dispatch one scoped slice"]
        T["Receives routing summary<br/>plus artifact paths"]
    end
    subgraph HOST["Host adapter"]
        B["Adapter supplies runtime session id"]
        W1["Progress watcher<br/>status only"]
        W2["Report watcher<br/>delivery only"]
    end
    subgraph CORE["Core + scheduler"]
        C["Validate role + limits"]
        H["Detached supervisor<br/>owns execution"]
        N["Finalize run<br/>classify + account + summarize"]
        R["Consolidated session report<br/>compact only"]
    end
    subgraph DB["SQLite control plane"]
        E[("run metadata<br/>status + paths")]
        O[("terminal metadata<br/>summary + accounting")]
    end
    subgraph FILES["File data plane"]
        F["request.json"]
        G["lifecycle.jsonl"]
        RET["return.md<br/>full child return"]
    end
    subgraph SUB["Subagent"]
        J["child harness process"]
        L{"exits"}
    end
    A --> B --> C --> E
    C --> F
    E --> H --> J --> L --> N
    N --> O
    N --> RET
    E --> G
    B -. starts .-> W1 -. polls .-> O
    B -. starts .-> W2 -. waits .-> R
    O --> R --> T
    RET -. path included .-> R
    style RET fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"02-supervisor-vs-watchers": {
"before": r'''flowchart LR
    subgraph MIXED["Current mental model"]
        A["Detached supervisor"]
        B["Background watchers"]
        C["Both are easy to confuse"]
    end
    A --> C
    B --> C
    C --> D["Unclear owner for execution,<br/>waiting, and delivery"]
    style D fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    subgraph SUP["Detached supervisor"]
        A["Start child harness"] --> B["Capture stdout/stderr"] --> C["Finalize run"]
    end
    subgraph WATCH["Background watchers"]
        W1["_await-run<br/>progress"]
        W2["_await-session-report<br/>delivery"]
    end
    subgraph STORE["Shared state"]
        DB[("SQLite status + metadata")]
        LOG["lifecycle log"]
    end
    A --> DB
    C --> DB
    C --> LOG
    W1 -. polls .-> DB
    W2 -. polls .-> DB
    style SUP fill:#e0f2fe,stroke:#0284c7,color:#075985
    style WATCH fill:#fef3c7,stroke:#d97706,color:#92400e
'''
},
"03-artifact-data-flow": {
"before": r'''flowchart LR
    subgraph DB["SQLite"]
        R[("runs row")]
        OUT["runs.result_output<br/>full final return"]
    end
    subgraph FILES["Scattered files"]
        REQ["state/requests/run-id.json"]
        LIFE["logs/run-id.jsonl"]
        SUP["logs/run-id.supervisor.log"]
        TR["transcript elsewhere"]
    end
    PARENT["Parent/report/debug may inline<br/>large or truncated text"]
    R --> OUT --> PARENT
    REQ --> PARENT
    LIFE --> PARENT
    SUP --> PARENT
    style OUT fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    subgraph DB["SQLite control plane"]
        R[("run metadata")]
        S["summary, status, accounting,<br/>artifact paths"]
    end
    subgraph FILES["Per-run file data plane"]
        REQ["state/runs/run-id/request.json"]
        LIFE["state/runs/run-id/lifecycle.jsonl"]
        SUP["state/runs/run-id/supervisor.log"]
        RET["state/runs/run-id/return.md"]
    end
    REPORT["Parent report<br/>compact routing summary"]
    READ["Host file-read tool<br/>chunked retrieval"]
    R --> S --> REPORT
    REPORT -. paths .-> FILES
    FILES --> READ
    style RET fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"04-finalization-decision-tree": {
"before": r'''flowchart LR
    EXIT(["Subagent exits"]) --> CAP["Capture output"] --> CLS{"Classify"}
    CLS --> SAVE["Store summary<br/>and full result_output in DB"]
    SAVE --> AUTO{"auto_verify?"}
    AUTO -- yes --> VER["Verifier prompt may inline<br/>builder result_output"]
    AUTO -- no --> REP["Maybe report"]
    VER --> REP
    style SAVE fill:#fee2e2,stroke:#dc2626,color:#991b1b
    style VER fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    subgraph CLASS["Classify"]
        EXIT(["Subagent exits"]) --> CAP["Capture output"] --> CLS{"done / failed / incomplete / cancelled"}
    end
    subgraph PERSIST["Persist"]
        META["DB metadata:<br/>status, summary, accounting, paths"]
        RET["return.md:<br/>full child return"]
    end
    subgraph CONT["Continuation"]
        AUTO{"successful exact builder<br/>with auto_verify?"}
        VER["Verifier gets compact summary<br/>and artifact paths"]
        REP["Report gate waits until<br/>all active subagents finish"]
    end
    CLS --> META
    CLS --> RET
    META --> AUTO
    AUTO -- yes --> VER --> REP
    AUTO -- no --> REP
    style RET fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"05-report-delivery-recovery": {
"before": r'''flowchart LR
    READY["All subagents terminal"] --> CLAIM["Claim report rows"] --> BUILD["Build report"] --> INJ{"Inject into parent?"}
    INJ -- success --> DONE["reported_at set"]
    INJ -- failure --> REL["Release claim"] --> GAP["Parent may not know<br/>report is pending or where evidence lives"]
    style GAP fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    subgraph NORMAL["Normal delivery"]
        READY["All subagents terminal"] --> CLAIM["Claim report rows"] --> BUILD["Compact report<br/>summary + paths + next hint"] --> DONE["reported_at set"]
    end
    subgraph RECOVER["Recovery surface"]
        REL["If injection fails:<br/>release claim"] --> HIST["history/status show<br/>undelivered runs"] --> PATHS["run IDs + artifact paths"] --> READ["read return.md/logs in chunks"]
    end
    BUILD -. injection failure .-> REL
    style RECOVER fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"06-auto-verifier-handoff": {
"before": r'''flowchart LR
    B["Builder completes"] --> OUT["Full builder result_output"] --> PROMPT["Verifier approved_context<br/>inlines full output"] --> V["Verifier run"]
    style PROMPT fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    B["Builder completes"] --> SUM["Compact builder summary"] --> PROMPT["Verifier prompt"] --> V["Verifier run"]
    B --> RET["return.md path"] --> PROMPT
    B --> LOG["lifecycle/supervisor log paths"] --> PROMPT
    WARN["Child output remains<br/>untrusted evidence"] --> PROMPT
    style RET fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"07-prompt-construction": {
"before": r'''flowchart LR
    ROLE["Role config"] --> PROMPT["Child prompt"]
    GOAL["Goal"] --> PROMPT
    CTX["Context"] --> PROMPT
    HINTS["Ad hoc hints and return formats"] --> PROMPT
    PROMPT --> CHILD["Subagent"]
    style HINTS fill:#fef3c7,stroke:#d97706,color:#92400e
''',
"after": r'''flowchart LR
    subgraph INPUTS["Prompt inputs"]
        ROLE["Role"]
        GOAL["Goal"]
        SCOPE["Scope + boundaries"]
        EVID["Prior evidence"]
        ART["Artifact paths"]
    end
    subgraph STANDARD["Standard sections"]
        PROMPT["Assignment<br/>constraints<br/>stop condition<br/>compact return format"]
    end
    subgraph CONFIG["Shared wording"]
        YAML["prompts.yaml owns<br/>generic hints"]
    end
    INPUTS --> PROMPT
    YAML --> PROMPT
    PROMPT --> CHILD["Subagent"]
    style STANDARD fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"08-debug-retrieval": {
"before": r'''flowchart LR
    CMD["orchestra debug run-id"] --> DUMP["One large inline bundle"] --> PARTS["run state, request,<br/>lifecycle, supervisor output,<br/>full return, transcript"] --> TRUNC["May exceed host caps<br/>model sees truncation"]
    style TRUNC fill:#fee2e2,stroke:#dc2626,color:#991b1b
''',
"after": r'''flowchart LR
    CMD["orchestra debug run-id"] --> MAN["Compact manifest"] --> PATHS["artifact paths + short previews"] --> READ["Read only needed files<br/>with offset / limit"]
    MAN --> OPT["Bulk content only by<br/>explicit inline/section flags"]
    style MAN fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
"09-prune-retention": {
"before": r'''flowchart LR
    CMD["prune"] --> PLAN["Find old rows and old files"] --> SCAT["Artifacts are scattered"] --> DEL{"--delete?"} --> RES["Delete/report"]
    style SCAT fill:#fef3c7,stroke:#d97706,color:#92400e
''',
"after": r'''flowchart LR
    CMD["prune"] --> PLAN["Plan phase always runs"] --> OWN["Owned paths per run:<br/>request, lifecycle, supervisor,<br/>return.md, transcript ref"] --> PREV["Preview by default"] --> DEL{"--delete?"}
    DEL -- no --> STOP["nothing changed"]
    DEL -- yes --> REMOVE["Delete owned files<br/>then DB row"] --> KEEP["Keep row if file delete fails"]
    style OWN fill:#dcfce7,stroke:#16a34a,color:#166534
'''
},
}

for base, variants in DIAGRAMS.items():
    for variant, content in variants.items():
        (DOCS / f"{base}-{variant}.mmd").write_text(content.rstrip() + "\n")
