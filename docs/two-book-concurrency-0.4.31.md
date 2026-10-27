# Two-book concurrency integration — 0.4.31

## Execution contract

- At most two books execute concurrently, with one active execution per book across its sessions. Changing sessions does not create an additional execution slot.
- Each accepted job freezes its actual writer and independent reviewer configuration. Later settings changes apply to subsequent jobs, not the already-running execution.
- Cancellation targets the selected book/session job individually; stopping one book does not stop the other. Saved content and history remain available.
- Switching books or opening settings leaves background jobs running. Existing draft, attachment, submission, and mutation guards remain in effect.
- After restart, interrupted work remains interrupted; it is not automatically replayed. Explicit operation replay handling is separate from automatic restart behavior.

## View and navigation integration

- Opening a book, navigating, or rendering a replacement view invalidates the old chat view and its polling timers before asynchronous rendering can reuse it. Per-book sessions and drafts are preserved; backend jobs are not cancelled.
- Job polling validates view epoch, hooks, project, selected session, and DOM root after asynchronous reads. A job that changes project/session identity does not navigate the displayed book to the new identity. The user is notified to choose the newly created book with the existing current-novel selector.
- Agent refresh callbacks reject stale view epochs and cross-book refresh requests, and validate again after reads before replacing workspace or rendering.
- The running-books overview shows titles and status. Raw project/session/job identifiers are kept inside collapsed technical details.
- GET `/api/settings/chat/activity` delegates directly to `chat_agent.activity()`. It does not fetch full book bodies or conversation histories. The overview uses a view-scoped, nonoverlapping lightweight poll with a three-second interval and bounded two-book output, including when the displayed book is idle.
- Local layout controls, including the hamburger menu, remain usable during local read/write busy sections and are dispatched before mutation guards. Settings entry shows a wait notice during such sections; background model jobs do not themselves block normal settings navigation. Other controls retain their original disabled state for restoration.
- Existing drawer layout, focus handling, request statistics, author policy, retries, and annotations are not redesigned by this integration.

## Verification status

The coordinator reports that prior fictional-data backend orchestration verification passed: two workers, global limit two, per-book limit one across sessions, replay handling, frozen writer/reviewer configuration, isolated cancellation, and independent chapter/review/maintenance work.

This development API did not run tests, builds, GUI verification, real-provider calls, or real-profile workflows. GUI behavior and real-provider execution remain unverified. Backend concurrency orchestration is preserved, with only the lightweight HTTP activity route added to its UI exposure. No version bump is included.

## Coordinator local delivery

The coordinator subsequently updated release metadata to 0.4.31 and completed bounded checks with fictional data and a stubbed network boundary. The real chat workers, versioned storage, review receipts and maintenance saves were exercised for two books. Same-book and third-book admission were rejected, blocked unbound requests created no orphan book, operation replay was idempotent, writer/reviewer snapshots stayed frozen, and cancellation affected only its own worker.

Actual frontend functions were exercised with isolated DOM/network fixtures: busy state left the hamburger enabled and body saves blocked; the click handler dispatched the menu before its busy guard and explained settings waits; old poll responses after switching could not refresh the other book, and moved jobs could refresh only the still-displayed book. This is function-level verification, not visual GUI acceptance. The real localhost activity endpoint returned task metadata while book-body access was deliberately prohibited. Request-statistics regression, Python AST, Node syntax and diff checks passed.

The independent local desktop directory is `G:/AGI/_two-book-0.4.31-delivery-20261027`. Desktop and fixed-folder shortcuts target its executable and retain the existing profile location. Build/resource/ASAR/source binding verification passed for 268 source files, with digest `ca14d2851e4e1884552c419e07e80393ce5dce5de164a0d28dba16ce7aaf1ec7`. There was no real-provider two-book writing or visual GUI acceptance, and no public push/release.
