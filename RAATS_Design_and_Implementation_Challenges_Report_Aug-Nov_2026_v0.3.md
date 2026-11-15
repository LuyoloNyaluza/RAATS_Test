# RAATS Design and Implementation Challenges Report
## An Agentic AI System for Adaptive Real-Time Trading Using LLM-Guided Strategy Selection and Python-Based Execution

**Reporting period:** August–November 2026  
**Prepared as:** Working MSc project development record  
**Version:** 0.3 | Evidence-based working draft  
**Last updated:** November 2026

---

## Document Purpose and Scope

This report documents the design and implementation challenges encountered during the development of the **Refined Architecture for Autonomous Trading System (RAATS)** from August to November 2026. It focuses on:

- Problems encountered and their technical causes
- Investigations performed and design decisions taken
- Implementation changes and their verification status
- Evidence available to verify each change

The report supports the MSc research record by making the system's development decisions traceable. It is **not** a claim that every identified issue has been fully resolved. Each entry is classified as **Resolved**, **Partially resolved**, or **Outstanding** according to the evidence currently available.

### Evidence and Status Rules

| Status | Criteria |
|--------|----------|
| **Resolved** | Correction implemented with direct evidence of successful operation or test result |
| **Partially resolved** | Workaround, partial correction, or protective mechanism exists, but wider issue remains or not fully verified |
| **Outstanding** | Problem identified, but implementation or verification not yet evidenced |

Dates reflect dated development discussions and test records. Where exact implementation date or successful verification was not recorded, the entry says so rather than inferring it.

---

## 1. Master Challenge Register

| ID | Date | Component | Challenge | Evidence/Verification | Status |
|----|------|-----------|-----------|----------------------|--------|
| CH-001 | 18 Aug 2026 | Environment / Local LLM | Local model and hardware constraints | Model installation evidenced; comparative performance and stable concurrent operation not documented | Partially resolved |
| CH-002 | 18 Aug 2026 | Data ingestion / news | Missing financial-news data directory | Code change proposed; successful rerun not captured | Partially resolved |
| CH-003 | 18 Aug 2026 | Agent / LangChain integration | Tool import and structured output mismatch | Correction proposed; no successful test output captured | Partially resolved |
| CH-004 | 29 Aug 2026 | LLM selection | Selecting suitable local model for RAATS | No controlled benchmark or integration result in record | Outstanding |
| CH-005 | 21 Sep 2026 | Agent / trading architecture | Separation of LLM recommendation and trade direction | Components reported present; end-to-end validation not captured | Partially resolved |
| CH-006 | 21 Sep 2026 | Market session / execution | Market-hours check not wired into live execution | Helper fix noted; no live-path verification recorded | Partially resolved |
| CH-007 | 17 Sep 2026 | Logging / timestamps | Incorrect or inconsistent trading timestamps | Fix reported completed; regression test not retrieved | Resolved |
| CH-008 | 19 Sep 2026 | Logging / file format | JSONL extension mismatch (JSON array vs line-delimited) | Extension changed to `.json`; parser test not retrieved | Resolved |
| CH-009 | 8–10 Oct 2026 | Monitoring / Prometheus | Node Exporter target unreachable from Docker | Both targets UP on 8 Oct; DOWN on 10 Oct means fix not robust | Partially resolved |
| CH-010 | 9 Oct 2026 | Monitoring / Grafana | Grafana provisioning failure and duplicate series | Provisioning restored; duplicate display issue unresolved | Partially resolved |
| CH-011 | 10 Oct 2026 | Performance testing | Need for measurable API load behaviour | 50/50 HTTP 200; 176.55 req/s; 27.39 ms avg; test < Prometheus scrape interval | Partially resolved |
| CH-012 | 14–15 Oct 2026 | Environment / deployment | Memory pressure from concurrent local services | Constraint measured; complete optimisation not evidenced | Partially resolved |
| CH-013 | 15 Oct 2026 | Testing / architecture integration | Compilation and isolated tests didn't establish dynamic workflow correctness | Integrated runtime behaviour unverified | Outstanding |
| CH-014 | 15 Oct 2026 | Backtesting / evaluation | Weak baseline simulation results | Equity $9,731.89; return -2.68%; Sharpe -3.403; max DD -6.99%; 13 NaN indicator errors | Partially resolved |
| CH-015 | 8 Nov 2026 | Memory / learning | Ticker history logged but not fully used for future discovery | Short-term ticker memory implemented, wired into live agent and batch loop, unit-tested (CH-033); outcome-based learning not evidenced | Partially resolved |
| CH-016 | 9–11 Nov 2026 | Market discovery | Yahoo screener pagination repeated first page | Root cause traced (CH-025): gainers window answered every screener with day-gainers list. Most-active now pages correctly (offsets 0–100, 25 rows each, 11 Nov log); day-gainers list 47 entries | Partially resolved |
| CH-017 | 11 Nov 2026 | Broker compatibility / discovery | Many discovered candidates not supported by FBS | "14 of 40" shortfall was collector defect (CH-025), now fixed: 40 of 40 collected on 11 Nov. FBS stock set size unproven | Partially resolved |
| CH-018 | 11 Nov 2026 | Batch orchestration / handoff | Dynamic manager initialised with empty candidate lists | Empty-list line at startup before first batch; 11 Nov batch 7 log shows populated lists after discovery | Partially resolved |
| CH-019 | 11 Nov 2026 | Deep-agent / LLM integration | Deep-agent creation failed due to missing Anthropic credentials | Fallback path runs stages directly; execution with intended local model not demonstrated | Partially resolved |
| CH-020 | 11 Nov 2026 | Reporting / batch lifecycle | Batch completed but reporting crashed on missing LiveSink method | LiveSink.final_outcome implemented (summary, event, rate-limited Discord alert) and smoke-tested; no live run reached it | Partially resolved |
| CH-021 | 12 Nov 2026 | Execution / market availability | Approved trade reported as opened while market was closed | Implementation and live verification pending | Outstanding |
| CH-022 | 12 Nov 2026 | Market discovery | Insufficient candidates from daily discovery sources | Source-order change documented; retrieval and runtime tests pending | Outstanding |
| CH-023 | 10–11 Nov 2026 | Market discovery | Short gainers list aborted batches | Batches no longer abort: 40/40 equities and 50-instrument universe on 11 Nov; offline stub test 37+3=40 | Resolved |
| CH-024 | 10 Nov 2026 | Market discovery / connectivity | DNS outage abandoned a batch | Price download retries implemented (3x with waits); not exercised in live outage | Partially resolved |
| CH-025 | 11 Nov 2026 | Market discovery / batch loop | Collected tickers discarded; gainers window masked most-active | Fixed; 11 Nov batch 7 log: gainers 10/40, most-active paged (offsets 0–100) to 40/40 | Resolved |
| CH-026 | 11 Nov 2026 | Broker compatibility / discovery | MT5 filter dropped 39 of 40 broker-supported candidates | Discovery now accepts symbol offered with full trading; RAATS_DISCOVERY_REQUIRE_QUOTE=1 restores strict test; stub test passes | Partially resolved |
| CH-027 | 11–12 Nov 2026 | Market discovery / reserve | Two reserve mechanisms; in-loop reserve under-filled | build_reserve gained fill_to_total and deep_fetcher; deep_most_active generator pages yfinance screener; stub test 9+9+12=30 | Partially resolved |
| CH-028 | 12 Nov 2026 | Batch orchestration | Batch with no tickers ended batch runner | Exhausted branch now reports, waits RAATS_EXHAUSTED_RETRY_SEC (900s), continues; Discord message reworded | Partially resolved |
| CH-029 | 11 Nov 2026 | Trading session / manager | Final INVEST target equals initial candidate count | Target should raise after reserve load to at least minimum threshold (5); one-line change proposed, not applied | Outstanding |
| CH-030 | 11–12 Nov 2026 | Execution / position sizing | Order size far below broker minimum on very small account | Not-placeable flag worked; oversize cap and approval ordering recommended, not applied | Partially resolved |
| CH-031 | 10–12 Nov 2026 | Broker compatibility | Broker–strategy mismatch and broker-specific eligibility | Cached catalogue, fail-open, not-tradable records scoped to broker server, bridge fallback, cache reset on switch; stub tests pass | Partially resolved |
| CH-032 | 10–11 Nov 2026 | Agent orchestration | Introducing Deep Agents without giving LLM control of trading | deep_batch.py (DeepBatchPipeline), one-line pipeline_cls change, per-stage skills, read-only AGENTS.md; scripted-model tests pass; live runs use direct-stage fallback | Partially resolved |
| CH-033 | 10–11 Nov 2026 | Memory / learning | Ticker memory robustness | Safe-append helper, chronological sort, no-objection for unparseable as_of; 5 unit tests pass | Resolved |

---

## 2. Detailed Challenge Records

### CH-001 | Local Model and Hardware Constraints
**Date:** 18 August 2026  
**Component:** Environment / Local LLM  
**Status:** Partially resolved  

1. **Challenge identification:** RAATS required local language models and embeddings, but model size had to be considered against available development hardware (16 GB RAM laptop).
2. **Technical cause:** Local inference competed with OS, IDE, Docker, and other services.
3. **Investigation:** Installed models included devstral-small-2 (15 GB), mistral (4.4 GB), nomic-embed-text (274 MB).
4. **Design decision:** Treat model selection as resource-constrained architectural decision; evaluate by task and deployment footprint.
5. **Implementation:** Ollama installed; multiple candidate models pulled.
6. **Verification:** Model installation evidenced; no controlled latency, quality, or concurrent-memory benchmark available.
7. **Remaining limitations:** Later observations showed memory pressure when Ollama and Docker ran together. Full resource budget and benchmark remain necessary.

---

### CH-002 | Missing Financial-News Data Directory
**Date:** 18 August 2026  
**Component:** Data ingestion / news  
**Status:** Partially resolved  

1. **Challenge identification:** News ingestion workflow encountered missing `data/raw/news/` directory when preparing financial-news output.
2. **Technical cause:** Application expected directory to exist before writing CSV file.
3. **Investigation:** Initialisation step identified as appropriate correction.
4. **Design decision:** Create parent directories automatically before writing news data.
5. **Implementation:** Pathlib-based change using `Path(...).mkdir(parents=True, exist_ok=True)` and writing `data/raw/news/financial_news.csv`.
6. **Verification:** Code correction proposed; successful rerun not captured.
7. **Remaining limitations:** Confirm directory created on clean checkout; CSV writable and readable.

---

### CH-003 | Tool Import and Structured-Output Mismatch
**Date:** 18 August 2026  
**Component:** Agent / LangChain integration  
**Status:** Partially resolved  

1. **Challenge identification:** LangChain agent test required changes to tool import and output returned by tool.
2. **Technical cause:** Tool decorator import and declared structured output type didn't align with test implementation.
3. **Investigation:** Recorded correction changed decorator import and returned typed output object.
4. **Design decision:** Use supported `tool` decorator import and return declared output model.
5. **Implementation:** Used `from langchain.tools import tool`, returned `WeatherOutput(description=result)`, configured Devstral via `model="ollama:devstral-small-2"`.
6. **Verification:** No successful test output captured.
7. **Remaining limitations:** Re-run test against installed LangChain and Ollama versions; record result.

---

### CH-004 | Choosing Appropriate Model for RAATS
**Date:** 29 August 2026  
**Component:** LLM selection  
**Status:** Outstanding  

1. **Challenge identification:** Different model options considered for agentic, coding, and retrieval tasks.
2. **Technical cause:** Models differed in capability, size, and suitability for local execution.
3. **Investigation:** GLM 5.3 Flash and GLM 5.3 discussed as candidate default and escalation models.
4. **Design decision:** Select models by measured task performance and resource usage, not size or claims.
5. **Implementation:** Discussion produced possible model-role allocation; no confirmed integration change recorded.
6. **Verification:** No benchmark or completed RAATS integration found.
7. **Remaining limitations:** Requires reproducible evaluation of response quality, latency, memory use, and tool-calling reliability.

---

### CH-005 | Separating LLM Recommendation from Trade Direction
**Date:** 21 September 2026  
**Component:** Agent / trading architecture  
**Status:** Partially resolved  

1. **Challenge identification:** Trading architecture needed to prevent LLM's investment recommendation from directly determining order side.
2. **Technical cause:** INVEST/HOLD is decision about whether to consider a trade; BUY/SELL is directional decision following system's quantitative logic.
3. **Investigation:** Codebase described as having `analyst.py`, `risk_manager.resolve_direction` and `executor.py` with pre-execution validation.
4. **Design decision:** Keep LLM output limited to INVEST/HOLD. Derive BUY/SELL from gradient through risk manager; validate trade before opening.
5. **Implementation:** `analyst.py` sets INVEST/HOLD; `risk_manager.resolve_direction` derives BUY/SELL from gradient; `executor.py` calls `validate_trade` before opening.
6. **Verification:** Components reported present; complete end-to-end tests not captured.
7. **Remaining limitations:** Test positive/negative gradients, zero-gradient expiry, HOLD handling, rejection by `validate_trade`.

---

### CH-006 | Market-Hours Check Not Wired into Live Pipeline
**Date:** 21 September 2026  
**Component:** Market session / execution  
**Status:** Partially resolved  

1. **Challenge identification:** Market-hours helper contained bug; helper fixed but not connected to live trading workflow.
2. **Technical cause:** Correct standalone helper doesn't protect system unless execution calls it before order submission.
3. **Investigation:** Distinction between helper correctness and integration into live path explicitly identified.
4. **Design decision:** Enforce market-session validation at execution boundary, not only during discovery or analysis.
5. **Implementation:** `is_market_open()` helper reported fixed; wiring into live pipeline outstanding.
6. **Verification:** No evidence of live execution test using corrected helper.
7. **Remaining limitations:** Later market-closed execution observations reinforce need for session gate and deferred-entry state.

---

### CH-007 | Standardising Timestamps to Pretoria Time
**Date:** 17 September 2026  
**Component:** Logging / timestamps  
**Status:** Resolved  

1. **Challenge identification:** Trading logs needed consistent local-time reference for review and reporting.
2. **Technical cause:** UTC timestamps require explicit conversion for South African time.
3. **Investigation:** Logging workflow reviewed; UTC-to-Pretoria conversion corrected.
4. **Design decision:** Use explicit timezone-aware conversion to Pretoria time (UTC+02:00).
5. **Implementation:** Timestamp conversion corrected in logging implementation.
6. **Verification:** Fix reported completed; no separate regression-test output retrieved.
7. **Remaining limitations:** Add test around date rollover and timezone-aware timestamp serialisation.

---

### CH-008 | Correcting JSON vs JSONL Mismatch
**Date:** 19 September 2026  
**Component:** Logging / file format  
**Status:** Resolved  

1. **Challenge identification:** File with `.jsonl` extension contained JSON array instead of line-delimited JSON objects.
2. **Technical cause:** Extension described different serialization format from actual content.
3. **Investigation:** Mismatch identified during logging output review.
4. **Design decision:** Use `.json` extension for array-formatted JSON, or change writer to emit one JSON object per line if JSONL required.
5. **Implementation:** Extension changed to `.json`; weekly rotation and Pretoria timezone retained.
6. **Verification:** Change reported completed; downstream parsing test not retrieved.
7. **Remaining limitations:** Confirm chosen format matches all readers and future memory-retrieval pipeline.

---

### CH-009 | Node Exporter Unreachable from Prometheus
**Date:** 8–10 October 2026  
**Component:** Monitoring / Prometheus  
**Status:** Partially resolved  

1. **Challenge identification:** Prometheus initially showed Node Exporter as DOWN while Agent API target was UP.
2. **Technical cause:** Configured host address not reachable from Docker network in WSL environment.
3. **Investigation:** Changing scrape target to WSL IP `172.30.103.42:9100` resulted in both targets UP on 8 October.
4. **Design decision:** Use reachable address and verify Prometheus target health; recognise WSL IP can change after restart.
5. **Implementation:** Prometheus target changed to WSL IP; Agent API target remained at `http://agent-api:8000/metrics`.
6. **Verification:** Both targets UP on 8 October; on 10 October, Node Exporter again DOWN with connection refused.
7. **Remaining limitations:** Make address resilient to WSL restarts; re-test target health after Docker/WSL restarts.

---

### CH-010 | Grafana Provisioning and Duplicate Metric Series
**Date:** 9 October 2026  
**Component:** Monitoring / Grafana  
**Status:** Partially resolved  

1. **Challenge identification:** Grafana provisioning initially failed; duplicate metric series appeared in dashboard panels.
2. **Technical cause:** YAML indentation error placed `path` under wrong configuration key; dashboard retained duplicate series despite query filtering.
3. **Investigation:** Provisioning YAML corrected; PromQL job filters added. Prometheus API returned one filtered memory series; Grafana still displayed duplicates.
4. **Design decision:** Correct provisioning syntax and verify metric uniqueness at both Prometheus query and dashboard layers.
5. **Implementation:** YAML indentation fixed; PromQL filters applied.
6. **Verification:** Dashboard provisioning restored; duplicate display behaviour not fully resolved.
7. **Remaining limitations:** Inspect actual provisioned dashboard query and panel transformations; verify after dashboard reload.

---

### CH-011 | Establishing Initial API Load-Test Baseline
**Date:** 10 October 2026  
**Component:** Performance testing  
**Status:** Partially resolved  

1. **Challenge identification:** Agent API needed repeatable test of request handling beyond single health-check.
2. **Technical cause:** Short burst test measures basic responsiveness but not sustained capacity or resource behaviour.
3. **Investigation:** Test run against `/health` with 50 requests, 5 workers. Results saved to `data\load_tests\load_test_20261010_134105.csv`.
3. **Design decision:** Use concurrent requests, capture response times, persist results for repeatability and comparison.
4. **Implementation:** Load test reported 50/50 HTTP 200, 100% success, 176.55 req/s, avg 27.39 ms, P95 197.51 ms, max 201.90 ms.
5. **Verification:** Test lasted ~0.28 seconds, shorter than 15-second Prometheus scrape interval. Initial smoke/load test, not sustained-load evaluation.
6. **Remaining limitations:** Run longer-duration tests; correlate request metrics with CPU, memory, container statistics.

---

### CH-012 | Memory Pressure During Concurrent Local Execution
**Date:** 14–15 October 2026  
**Component:** Environment / deployment  
**Status:** Partially resolved  

1. **Challenge identification:** Running local LLM inference, Docker services, and development tools together caused high memory usage.
2. **Technical cause:** Combined memory footprint of model, containers, IDE, OS approached laptop capacity.
3. **Investigation:** Ollama observed using ~5 GB; total system memory reached ~95%.
4. **Design decision:** Treat hardware limits as deployment constraint; avoid assuming all services run concurrently without resource planning.
5. **Implementation:** Model sizes and memory use reviewed; smaller models and staged service use considered.
5. **Verification:** Memory pressure observed; no complete optimisation benchmark captured.
6. **Remaining limitations:** Measure peak memory for representative workloads; document stable model/container combination.

---

### CH-013 | Insufficient End-to-End Verification of Dynamic Trading Behaviour
**Date:** 15 October 2026  
**Component:** Testing / architecture integration  
**Status:** Outstanding  

1. **Challenge identification:** Dynamic workflow contained several interacting behaviours not verifiable by compilation alone.
2. **Technical cause:** Compilation and linting don't establish correct state transitions, shared RiskManager use, or live-position lifecycle behaviour.
3. **Investigation:** Stub-based tests covered parts of pipeline; dynamic workflow only compiled/linted in recorded review.
4. **Design decision:** Validate complete runtime flow, including shared RiskManager state, open-position monitoring, HOLD replacement, neutral sentiment handling.
5. **Implementation:** Component-level checks performed; full integration evidence not available.
6. **Verification:** No end-to-end test result recorded for complete dynamic workflow.
7. **Remaining limitations:** Create deterministic integration tests with controlled broker and market-data responses.

---

### CH-014 | Negative Baseline Simulation and Indicator Errors
**Date:** 15 October 2026  
**Component:** Backtesting / evaluation  
**Status:** Partially resolved  

1. **Challenge identification:** Initial AAPL simulation produced negative return and Sharpe ratio with indicator errors.
2. **Technical cause:** Baseline strategy and indicator pipeline generated weak results; 13 NaN indicator errors recorded.
3. **Investigation:** Simulation covered 16 March to 15 September 2026, starting with $10,000.
4. **Design decision:** Preserve baseline as comparator; investigate indicator validity and pre-trade validation before evaluating improvements.
5. **Implementation:** Baseline run executed using simulation workflow.
6. **Verification:** Final equity $9,731.89; return -2.68%; Sharpe -3.403; max DD -6.99%; 3 closed trades; 13 NaN indicator errors.
6. **Remaining limitations:** Proposed Pre-Trade Validation Stage requires comparable experiment before effect can be claimed.

---

### CH-015 | Making Ticker History Useful to Future Discovery
**Date:** 8 November 2026  
**Component:** Memory / learning  
**Status:** Partially resolved  

1. **Challenge identification:** System needed to learn from previous ticker analyses for later candidate identification.
2. **Technical cause:** Persisting JSONL records alone doesn't provide semantic retrieval, outcome matching, or integration into discovery decisions.
3. **Investigation:** Identified need for persistent ticker memory, retrieval of returning candidates, lifecycle tracking.
4. **Design decision:** Use stored analysis and outcomes to support future candidate selection while avoiding repeats across processed, rejected, active, waiting, and final-invest lists.
5. **Implementation:** JSONL logging and learning-oriented retrieval design discussed; complete integrated retrieval path not confirmed.
6. **Verification:** No verified test showed previously analysed ticker retrieved and used in later discovery cycle.
**Update (12 Nov 2026):** Short-term ticker memory implemented as append-only event log with advisory rules (rejected trades, losing closes, tickers broker doesn't offer), used by live agent and batch pipeline, unit-tested (CH-033). Outcome-based learning, retrieval of returning candidates, and later discovery cycle using them still not demonstrated.

---

### CH-016 | Repeated Yahoo Screener Pages During Pagination
**Date:** 9–11 November 2026  
**Component:** Market discovery  
**Status:** Partially resolved  

1. **Challenge identification:** Yahoo screener calls returned 47 symbols at offset 0 and same page again at offset 47.
2. **Technical cause:** Observed yfinance/Yahoo response didn't return distinct subsequent page for requested offset.
3. **Investigation:** Runtime logs showed repeated-page detection stopping scan rather than processing same symbols indefinitely.
4. **Design decision:** Detect repeated page signatures and stop safely; supplement candidate pool through other discovery sources.
5. **Implementation:** Scanner included repeated-page detection. Reserve sources used when screener sources didn't fill required pool.
6. **Verification:** Infinite/repeated scan avoided, but deeper pagination remained unavailable.
**Update (12 Nov 2026):** Root cause traced in CH-025: runner's gainers window answered every screener call with day-gainers list, so second "page" and most-active call both returned same 47 symbols. With real module used for most-active, 11 November log shows pages at offsets 0, 25, 50, 75, 100. Day-gainers list stayed at 47 entries, consistent with full size.

---

### CH-017 | Yahoo Candidates Rejected by FBS Broker Catalogue
**Date:** 11 November 2026  
**Component:** Broker compatibility / discovery  
**Status:** Partially resolved  

1. **Challenge identification:** Yahoo discovery returned many tickers not accepted by FBS broker-symbol filter.
2. **Technical cause:** Yahoo's equity universe and broker's available instruments are different sets; broker naming varies.
3. **Investigation:** Runtime reported 578 symbols in FBS-Real catalogue, 102 unsupported candidates skipped, only 14 of 40 equities collected after discovery and reserve.
4. **Design decision:** Keep broker eligibility as mandatory filter; continue through alternative sources; distinguish unsupported instruments from temporary broker/API failures.
5. **Implementation:** `_add_unique` path applies broker acceptance and records skipped candidates; reserve candidates also passed through validation.
6. **Verification:** Filter operating; run didn't reach 40 equities. Result doesn't establish FBS offers only 14 equities.
**Update (12 Nov 2026):** "14 of 40" result caused by collector defect (CH-025), not only catalogue; after fix 40 of 40 broker-supported equities collected on 11 November. Separate problem then removed 39 of them at MT5 filter (CH-026). Whether FBS offers only small stock set still unestablished.

---

### CH-018 | Dynamic Manager Started with Empty Lists
**Date:** 11 November 2026  
**Component:** Batch orchestration / handoff  
**Status:** Partially resolved  

1. **Challenge identification:** Startup log showed Top-50 universe, initial active list, and waiting list all at zero.
2. **Technical cause:** Discovery output may not have been handed to manager at correct time or assigned to expected state fields.
3. **Investigation:** Log showed empty manager state before subsequent discovery stage ran and populated candidate results.
4. **Design decision:** Trace batch startup, discovery completion, manager initialisation; ensure manager receives completed discovery outputs.
5. **Implementation:** No confirmed code change captured.
6. **Verification:** No post-fix runtime log showing populated manager lists available.
**Update (12 Nov 2026):** 11 Nov batch 7 log shows empty-list line at start-up, before any batch, and later initialisation with populated lists (Top-50: 1, active: 1) after discovery. Consistent with start-up placeholder rather than hand-off fault; should be confirmed in code.

---

### CH-019 | Deep-Agent Failed Due to Missing Anthropic Credentials
**Date:** 11 November 2026  
**Component:** Deep-agent / LLM integration  
**Status:** Partially resolved  

1. **Challenge identification:** Deep-agent runner failed to initialise because no Anthropic API key provided.
2. **Technical cause:** Agent creation path defaulted to Anthropic-backed model when intended provider not explicitly configured.
3. **Investigation:** Log recorded authentication failure and showed direct-stage fallback running discovery, scoring, analysis.
4. **Design decision:** Configure intended model provider explicitly; ensure fallback behaviour is deliberate, observable, tested.
5. **Implementation:** Fallback path ran stages directly after agent failed.
6. **Verification:** Fallback execution observed; successful deep-agent execution with intended local model not demonstrated.
**Update (12 Nov 2026):** With RAATS_DEEP_MODEL unset, pipeline now skips agent, prints one notice, runs three stages directly; 11 Nov batch 7 log shows this and no authentication error. Execution through intended local model still not demonstrated (CH-032).

---

### CH-020 | Missing LiveSink.final_outcome Method
**Date:** 11 November 2026  
**Component:** Reporting / batch lifecycle  
**Status:** Partially resolved  

1. **Challenge identification:** Batch completed, but background runner crashed calling `sink.final_outcome(self.outcomes)`.
2. **Technical cause:** Caller expected method not implemented on `LiveSink` object.
3. **Investigation:** Traceback identified call site in `trading_loop_dynamic.py` and missing method on `LiveSink`.
4. **Design decision:** Align caller with sink's actual reporting interface or implement missing method consistently.
5. **Implementation:** No correction evidenced in retrieved discussion.
6. **Verification:** Batch reached `BATCH_COMPLETED`, but reporting thread raised AttributeError.
**Update (12 Nov 2026):** LiveSink.final_outcome implemented: prints batch summary, records event, sends Discord alert limited to once per hour. Smoke-tested with stand-in object. Meaning later changed: now reports batch that found no tickers before next batch starts (CH-028). No live run has reached it since.

---

### CH-021 | Approved Trade Reported as Opened While Market Was Closed
**Date:** 12 November 2026  
**Component:** Execution / market availability  
**Status:** Outstanding  

1. **Challenge identification:** Log showed approved NOW candidate and dry-run message stating SHORT position opened, while manual broker attempt found market closed.
2. **Technical cause:** Instrument support or approval doesn't prove instrument is currently inside trading session or valid quote/order can be submitted.
3. **Investigation:** Proposed execution review identified need to check symbol trade mode, trading sessions, current tick freshness, terminal connectivity, order validation immediately before execution.
4. **Design decision:** Use three explicit outcomes: OPEN when all checks pass; DEFER when market closed; REJECT when instrument or order invalid. Revalidate signal, price, direction, stop, target, size, risk before deferred entry retried.
5. **Implementation:** Market-availability gate and deferred-entry queue proposed. Dry-run mode should apply same gate and report `TRADE DEFERRED`, `MARKET_CLOSED`, `WAITING_FOR_SESSION` rather than `OPENED`.
6. **Verification:** No implementation or live verification recorded.
7. **Remaining limitations:** Inspect actual execution function and approval-to-execution handoff to insert gate without changing discovery/batch logic.

---

### CH-022 | Adding Yahoo 52-Week Gainers Before Reserve Sources
**Date:** 12 November 2026  
**Component:** Market discovery  
**Status:** Outstanding  

1. **Challenge identification:** Daily gainers and most-active sources may not provide enough distinct broker-supported equities to fill target pool.
2. **Technical cause:** Source coverage, repeated pagination, broker filtering, exclusion/deduplication rules reduce usable candidates.
3. **Investigation:** Requested source order confirmed: day gainers, most-active, 52-week gainers, reserve sources, emergency fallback.
4. **Design decision:** Add 52-week gainers as independent source before reserve loading while preserving existing `_add_unique` broker and exclusion checks.
5. **Implementation:** Revised caller block shown using `_fetch_52_week_gainers()` and `_add_unique()`. Retrieval helper not yet implemented in evidence.
6. **Verification:** No runtime test or evidence of retrieved 52-week gainers recorded.
**Update (12 Nov 2026):** 52-week gainers source not implemented in later sessions. Candidate shortfall addressed through corrections in CH-025 and reserve top-up in CH-027; this entry remains open as additional source.

---

### CH-023 | Discovery Returned Fewer Than 40 Equities and Aborted Batches
**Date:** 10–11 November 2026  
**Component:** Market discovery  
**Status:** Resolved  

1. **Challenge identification:** Batches 1 and 3 on 10 November abandoned with ValueError: Expected 50 instruments, but built 43/42. Yahoo returned only 33 and 32 usable gainers (37 raw on test day), fewer than 40 required.
2. **Technical cause:** Discovery asked Yahoo for exactly 40 gainers then removed symbols failing equity filter (letters only, ≤5 chars). Shortfall left universe below 50; strict count check raised. Emergency fallback list contained delisted ticker (WBA, Walgreens taken private August 2025).
3. **Investigation:** Run logs compared with discovery and batch-loop code. Web search confirmed WBA delisting.
4. **Design decision:** Short list must never abort batch. Fetch deeper than needed, filter, then top up from ordered sources (each with duplicate/exclusion checks): Yahoo day gainers, Yahoo most-active, reserve sources, emergency list (batch 1 only). Later batches report "exhausted" instead of padding with unrelated large caps.
5. **Implementation:** `get_tickers_from_gainers_feed` rewritten around shared `_add_unique` helper; request size raised to 250 rows; top-up chain added. WBA removed from emergency list (51 tickers remain).
5. **Verification:** Offline stub test: 37 gainers + 3 most-active = 40 distinct tickers. Live log 11 Nov (batch 7): "Successfully collected 40 broker-supported equities" and Equities 40 + Commodities 5 + Currencies 5 = 50.
7. **Remaining limitations:** Delisted or bad symbol elsewhere in emergency list could still be dropped silently after price download; emergency list needs periodic maintenance.

---

### CH-024 | Network Outage During Discovery
**Date:** 10 November 2026  
**Component:** Market discovery / connectivity  
**Status:** Partially resolved  

1. **Challenge identification:** Batch 2 ran while machine couldn't resolve Yahoo hosts (curl error 6). Emergency list supplied 50 instruments, all 50 price downloads failed, batch ended with ValueError: No valid market pricing data returned. Discord alert also failed (discord.com unresolved).
2. **Technical cause:** Local DNS or internet loss. Code treated first empty download as final.
3. **Investigation:** yfinance errors in log showed failure was connectivity, not delisting (yfinance printed "possibly delisted" for every ticker).
4. **Design decision:** Treat empty download as possibly transient: retry with increasing waits, then abandon batch cleanly if still fails.
5. **Implementation:** `get_previous_session_returns` now retries `yf.download` three times (5s, then 10s waits).
5. **Verification:** Change compiled; not exercised by test or real outage.
6. **Remaining limitations:** Add connectivity pre-check before batch starts; queue alerts while Discord unreachable; avoid emergency list when offline (it can't be priced anyway).

---

### CH-025 | Collected Tickers Discarded; Gainers Window Masked Most-Active
**Date:** 11 November 2026  
**Component:** Market discovery / batch loop  
**Status:** Resolved  

1. **Challenge identification:** 11 Nov log showed day_gainers accepting 10 of 47, most_actives returning same 47 with 0 accepted, "Still short by 40", final result only 14–16 tickers from reserve.
2. **Technical cause:** Two defects: (a) In revised collector, accepted tickers kept in local list never copied to returned list, so 10 gainers and any most-active names discarded. (b) Batch runner replaces yfinance with gainers window object answering every `screen()` call with day-gainers list, ignoring query. Most-active returned same 47 gainers, all already seen, explaining identical counts and repeated-page stop.
3. **Investigation:** Log arithmetic (10 accepted but "short by 40") exposed first defect; reading window class exposed second.
4. **Design decision:** Keep reference to real yfinance module for every screener other than day gainers; collect directly into returned list; apply used-ticker exclusion to every source; walk whole gainers list before moving to most-active.
5. **Implementation:** Module-level `_REAL_YF` reference and rewritten `get_tickers_from_gainers_feed`; page size raised to 250.
5. **Verification:** Stub test imitating window: 10 gainers + 20 most-active + 2 reserve = 32 distinct tickers; later batch excluded all used tickers. Live log 11 Nov (batch 7): gainers 10/40, then most-active pages at offsets 0–100 reaching 40/40.
7. **Remaining limitations:** Predefined day-gainers list held 47 entries in observed run; later sources carry shortfall. Deeper gainers pagination not available.

---

### CH-026 | MT5 Filter Dropped 39 of 40 Broker-Supported Candidates
**Date:** 11 November 2026  
**Component:** Broker compatibility / discovery  
**Status:** Partially resolved  

1. **Challenge identification:** 11 Nov log showed "Tradable on broker: 1 / 40" although broker catalogue accepted all 40 equities. Later, reserve's own check accepted MU, AVGO, COST, which discovery had just dropped.
2. **Technical cause:** Most likely cause: `enrich_final_invest` marks symbol tradable only when bid and ask both non-zero. Outside exchange session a stock CFD has no live quote, so almost every equity failed a test about market hours, not instrument eligibility.
3. **Investigation:** Compared discovery filter with reserve's `is_mt5_tradable` check and `enrich_final_invest`, found three layers answered "tradable?" differently.
4. **Design decision:** Discovery decides eligibility (symbol offered, FULL trade mode). Live quote checked when order planned, where it already is.
5. **Implementation:** `apply_mt5_filter` now accepts symbol offered with full trading; `RAATS_DISCOVERY_REQUIRE_QUOTE=1` restores strict test.
5. **Verification:** Stub test: 5 of 5 tickers pass by default, 1 of 5 with strict setting. Revised file reported to resolve problem; no live log captured yet.
7. **Remaining limitations:** Capture live run log. Same quote dependence affects CH-021 (market closed).

---

### CH-027 | Two Reserve Mechanisms; In-Loop Reserve Under-filled
**Date:** 11–12 November 2026  
**Component:** Market discovery / reserve  
**Status:** Partially resolved  

1. **Challenge identification:** RAATS has two reserve uses: (1) discovery tops up when gainers < 40; (2) trading loop adds one-time reserve of 30 (10 each from trending, world indices, most-active) when top 50 exhausted and <5 tickers reached final INVEST. 11 Nov log showed second added only 25 (9, 9, 7).
2. **Technical cause:** Each source supplies one page (~25 rows). Symbols that were duplicates or untradable on broker skipped without replacement; most world indices untradable on FBS.
3. **Investigation:** Yahoo most-active page shows 25 rows per page and ignored larger count parameter; deeper source needed.
4. **Design decision:** Keep both triggers and duplicate checks. Top up any shortfall from deeper most-active pages with same duplicate and tradability checks, so reserve reaches 30. Discovery's own reserve call doesn't use top-up.
5. **Implementation:** `build_reserve` gained `fill_to_total` and `deep_fetcher`; `deep_most_active` generator pages yfinance screener (route that worked in 11 Nov log); all picked names interleaved.
5. **Verification:** Stub test: 9 + 9 + 12 = 30 distinct tradable tickers, none already known; with `fill_to_total` off result is 25; failing deep source falls back to 25. Not yet run live.
7. **Remaining limitations:** Confirm paging at runtime. World-indices source contributes little on FBS.

---

### CH-028 | Batch with No Tickers Ended Batch Runner
**Date:** 12 November 2026  
**Component:** Batch orchestration  
**Status:** Partially resolved  

1. **Challenge identification:** When discovery returned fewer tickers than batch needed, runner reported "exhausted" and stopped, so no further batch ran that session. Requirement: batch with no tickers should be followed by new batch.
2. **Technical cause:** Runner treated exhausted outcome as final (break), while other outcomes (macro block, rejection, empty) waited and continued.
3. **Investigation:** Read `BatchRunner.run` and outcome handling for each batch result.
4. **Design decision:** On exhausted: report, wait, then start full new discovery, because Yahoo's lists change during the day.
5. **Implementation:** Exhausted branch now reports (guarded against errors), waits `RAATS_EXHAUSTED_RETRY_SEC` (default 900s), continues. Discord message reworded to say next batch starts automatically.
5. **Verification:** Fake-sink test of loop: outcomes exhausted, empty, exhausted, handed, stopped all ran, with two 900-second waits and two reports. Not yet observed in live run.
6. **Remaining limitations:** If every discovery stays short, loop repeats every 15 minutes; add daily cap or escalating alert.

---

### CH-029 | Final INVEST Target Equals Initial Candidate Count
**Date:** 11 November 2026  
**Component:** Trading session / manager  
**Status:** Outstanding  

1. **Challenge identification:** In batch 7 only AMD survived discovery, so manager started with Target final INVEST of 1. AMD failed RGR screen, reserve loaded 25 tickers, MU and ^GSPC tried, COST approved, session stopped at "1/1".
2. **Technical cause:** `max_active_positions` set to length of initial active list when manager created. Loading reserve adds candidates but doesn't raise target.
3. **Investigation:** Log sequence (target 1, reserve 25, stop at 1/1) and manager constructor compared.
4. **Design decision:** After reserve load, raise target to at least minimum final-INVEST threshold (5) so reserve can serve its purpose.
5. **Implementation:** One-line change inside reserve-loading method proposed; not applied because reserve logic was to be left unchanged.
5. **Verification:** No verification yet.
7. **Remaining limitations:** Decide target rule and test with small initial list.

---

### CH-030 | Order Size Far Below Broker Minimum on Very Small Account
**Date:** 11–12 November 2026  
**Component:** Execution / position sizing  
**Status:** Partially resolved  

1. **Challenge identification:** 11 Nov run showed MT5 balance $0.74. COST sized at 0.00007 units vs minimum 0.01 lot (plan reported 14,407x size RAATS wanted); earlier ORKA plan showed 0.00067 units. Batch still went to Discord for approval.
2. **Technical cause:** RAATS sizes risk in fractional units, but MT5 stock CFDs trade in lots with minimum; smallest tradable position can be thousands of times larger than sized risk. Rounding up silently takes far more risk than intended.
3. **Investigation:** Sizing adapter read: rounds lots down and flags any trade below broker minimum. Live agent's small-account rule opens minimum lot when account under $200 unless oversize cap set; cap defaults to 0 (no cap).
4. **Design decision:** Never round up silently. Mark such trades not placeable; treat oversize cap and minimum-balance gate as risk controls rather than optional settings.
5. **Implementation:** Not-placeable flag already existed and worked (evidence in log). Cap value and approval-after-placeability ordering recommended, not applied.
5. **Verification:** Log confirms correct flagging. Balance gate behaviour not traced.
6. **Remaining limitations:** Set sensible oversize cap, confirm balance gate, check placeability before sending approval request. Broker with fractional shares would suit sizing model but needs new execution adapter.

---

### CH-031 | Broker–Strategy Mismatch and Broker-Specific Eligibility
**Date:** 10–12 November 2026  
**Component:** Broker compatibility  
**Status:** Partially resolved  

1. **Challenge identification:** Top-gainers strategy draws mid/small caps; broker offers limited set. ORKA and CHDN not tradable on Exness; on FBS, 10 of 47 gainers offered from 578-symbol list. Discovery broker filter depended on `RAATS_USE_MT5` being set, while live mode detected MT5 automatically.
2. **Technical cause:** Yahoo's universe and broker's symbol list are different sets; broker naming varies (suffixes, prefixes).
3. **Investigation:** Symbol catalogue, ticker-memory records, bridge reviewed; exercised with stubbed MT5.
4. **Design decision:** Read broker's own symbol list once, cache it per server, filter discovery with it, remember "not offered" per broker, reset resolution caches when account changes.
5. **Implementation:** `broker_symbols.py` (cached catalogue, fail-open), not-tradable records scoped to broker server in ticker memory, bridge fallback to catalogue, cache reset when broker switch detected (added during review).
5. **Verification:** Stub tests: fresh fetch starts 5-minute timer; same server not refetched; switch loads new catalogue and empties old resolutions; not-offered record blocks ORKA on one server but not another; failing terminal falls back to loaded catalogue. 11 Nov log shows broker filter running with `RAATS_USE_MT5` unset.
7. **Remaining limitations:** Switch noticed within ~5 minutes. Records saved before server name stored apply to every broker. With small stock catalogue, structural mismatch remains; option is fallback ranked from broker's own stock list.

---

### CH-032 | Introducing Deep Agents Without Giving LLM Control of Trading
**Date:** 10–11 November 2026  
**Component:** Agent orchestration  
**Status:** Partially resolved  

1. **Challenge identification:** Design called for main agent with discovery, scoring, analysis subagents (Deep Agents), with prompts, tools, permissions, around functions not to be changed.
2. **Technical cause:** LLM is non-deterministic while trading stages are order-dependent. DataFrames and trading manager can't pass through model's context. Small local model may misorder or repeat calls; repeated analysis call would send Discord approval twice.
3. **Investigation:** Course examples on subagent teams, dynamic subagents, skills, memory compared with existing three-stage pipeline with `pipeline_cls` hook.
4. **Design decision:** Use ordinary subagent team (fixed roles, not dynamic subagents). Each subagent gets one tool calling existing stage unchanged; data stays in Python, only short summaries reach model; each stage runs once and only after predecessor; no agent has order, MT5-write, or Discord tool; file permissions scope each stage's notes; code runs any stage agent didn't.
5. **Implementation:** `deep_batch.py` (DeepBatchPipeline), one-line `pipeline_cls` change in `live_agents.py`, per-stage skills (SKILL.md plus reference.md), read-only AGENTS.md memory. Position engine stays plain code.
5. **Verification:** Scripted-model tests: ordered calls, out-of-order and repeated calls, model calling no tools, unreachable model, repeated stage calls all ran each stage exactly once. Tests caught YAML error in skill description (colon), fixed. Live runs so far used direct-stage fallback.
7. **Remaining limitations:** Run with intended local model; give Ollama larger context window; framework's prompts are large.

---

### CH-033 | Ticker Memory Robustness
**Date:** 10–11 November 2026  
**Component:** Memory / learning  
**Status:** Resolved  

1. **Challenge identification:** Code review of ticker-memory event log (reject and loss cool-downs) found three defects: crash could leave partial last line, so next event glued onto it; "newest first" relied on file order; unreadable `as_of` date fell back to current time.
2. **Technical cause:** Plain append without checking final newline; no sorting by event time; fail-to-now default in `check()`.
3. **Investigation:** Defects found by reading code; unit test written for each fixed behaviour.
4. **Design decision:** Appends must be crash-safe, ordering from event time, bad historical date must never expose later events (look-ahead).
5. **Implementation:** Safe-append helper, chronological sort, no-objection result with warning for unparseable `as_of`.
5. **Verification:** Five unit tests pass: Friday rejection blocks Saturday and Monday but not Tuesday; truncated line followed by new record loads both; `as_of="garbage"` gives no objection; future event ignored; out-of-order writes still honour newest loss.
7. **Remaining limitations:** File never pruned, meant for one process, uses local time. Profitable close doesn't yet end loss cool-down.

---

## 3. Cross-Cutting Design Lessons

1. **Separate decision authority from execution authority:** LLM recommends INVEST/HOLD; deterministic gradient and risk-management logic determine direction and validate execution.

2. **Validate at the point of action:** Market-hours helper insufficient unless execution path invokes it immediately before order. Same principle applies to broker compatibility and order checks.

3. **Treat external providers as unreliable dependencies:** Yahoo pagination, broker symbol catalogues, WSL networking, model-provider authentication all require explicit error handling and observable fallbacks.

4. **Distinguish permanent ineligibility from temporary failure:** Ticker rejected because broker doesn't offer it ≠ ticker that couldn't be checked because MT5/API temporarily unavailable.

5. **Persisted data must be operationally useful:** Logs and ticker histories become memory only when retrievable, matchable, deduplicable, usable in later decisions.

6. **Verify the whole workflow:** Module compiling, Prometheus query returning one series, batch reaching completion marker ≠ complete user-facing workflow correct.

6. **Measure before claiming improvement:** AAPL baseline and API load test provide initial measurements; sustained-load tests and comparable strategy evaluations still needed.

7. **The code, not the model, is the guarantee:** Agent layer coordinates deterministic stages, but each stage must run once, in order, and code must run any stage agent didn't (CH-032).

7. **Adapters must not change interface semantics silently:** Window object answering every screener query with gainers list looked like Yahoo limitation (CH-025).

8. **Layers must agree on what "tradable" means:** Catalogue check, live-quote check, reserve's own check gave different answers; eligibility in discovery, live quote at order time (CH-026).

8. **A fallback must be able to change the stopping rule:** Reserve loading 25 tickers useless if target stays at initial list size (CH-029).

9. **Safety limits that default to off are not limits:** Oversize cap of 0 and approval request before placeability known leave risk control to chance (CH-030).

10. **Fetch deep, filter, then trim:** Asking external source for exactly the number needed fails as soon as a filter removes one item (CH-023).

---

## 4. Outstanding Work and Evidence Required

| Outstanding Item | Evidence to Collect |
|------------------|---------------------|
| Market-session gate and deferred entry (CH-021) | Execution function, session-check result, dry-run closed-market log, successful retry with fresh signal and broker validation |
| 52-week gainers source (CH-022) | Helper implementation, sample parsed tickers, broker-filter counts, duplicate/exclusion tests, runtime discovery log |
| Discovery-to-manager handoff (CH-018) | Code confirmation zero-count line is start-up placeholder; 11 Nov batch 7 log (populated lists after discovery) |
| Final INVEST target after reserve load (CH-029) | Manager code, test with one-ticker initial list, live log showing target raised and reached |
| Oversize cap and approval ordering (CH-030) | Configured cap value, balance-gate trace, log where non-placeable plan not sent for approval |
| Live confirmation of CH-026, CH-027, CH-028 | One live log each: MT5 filter with market closed, in-loop reserve of 30, new batch after exhausted |
| Deep agents with local model (CH-032) | Provider/model configuration, successful agent-driven batch, context-window setting used |
| Offline and Discord-unreachable handling (CH-024) | Connectivity pre-check, alert queue, test/live run with network down |
| Ticker memory retrieval (CH-015) | Stored ticker record, retrieval query, deduplication behaviour, later discovery cycle using retrieved candidate |
| Sustained API load test (CH-011) | Longer test duration, concurrent users, response-time percentiles, error rate, CPU/memory, Prometheus/Grafana evidence |
| Integrated trading tests (CH-013) | Tests covering INVEST/HOLD, positive/negative/zero gradient, risk limits, open-position monitoring, market closure, deferred retry |

---

## 5. Implementation Summary: Phase 1 Execution Flow (November 2026)

### Completed Phase 1 Changes

**Files Modified:**
- `src/agents/live_agents.py` - Complete rewrite with Phase 1 execution flow
- `src/notifications/discord_notifier.py` - Added `send_trade_refreshed()` method
- `src/data/mt5_orders.py` - Added MT5 return code 10016 (algo disabled) handling
- `src/agents/trading_loop_dynamic.py` - Minor batch relaxation fix

### Phase 1 Execution Flow

```
1. Analysis → preliminary params
2. Discord: APPROVE / REJECT
3. User: APPROVE
4. Post-approval refresh → fresh MT5 quote → recalc all params
5. Trade Refreshed notification (informational, no buttons)
6. Entry timer starts (15-30s)
7. Timer ends → fresh executable-side quote (Ask for BUY, Bid for SELL)
8. Price deviation ≤ $0.20?
   YES → Re-run risk/margin checks → Execute
   NO → Recalc → Fresh Discord approval (max 2 retries)
```

### Environment Variables (Phase 1)
```bash
RAATS_EXEC_TOLERANCE_PRICE=0.20
RAATS_MAX_REVALIDATIONS=2
```

### Deferred to Phase 2+
- Per-trade ceiling, combined open risk, daily loss limit, margin utilization
- Adaptive ATR (1.2/1.5), gradient factor cap (1.5)
- Market hours handling
- Min-lot oversize rejection, daily P&L persistence

---

## 5. Notes on Evidence Quality and Report Finalisation

This version (0.3) is a working draft compiled from:
- Dated development discussions and recorded runtime outputs
- Week setup files (Week1–Week10)
- Source code inspection (live_agents.py, discord_notifier.py, mt5_orders.py, trading_loop_dynamic.py)
- Existing challenges report v0.2
- Git diffs and syntax verification

**Evidence types:**
- **Live log** – A run of the system
- **Stub test** – Isolated test with stand-in Yahoo, MT5, or model components
- **Unit test** – Isolated component test

Stub and unit tests do not replace live runs; entries relying on them are marked **Partially resolved** unless a live log exists.

Before finalising, reconcile each entry against relevant commit, source file, test output, or screenshot. Where a fix was implemented after discussion date, update status and add verification date. Do not change to **Resolved** solely because code was proposed or module compiled.

This report complements, rather than replaces, formal methodology, system architecture, implementation, and evaluation chapters of the MSc project.

---

*End of Report v0.3*