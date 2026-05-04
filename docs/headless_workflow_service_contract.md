# Headless Workflow Service Contract

## 1. Mục tiêu

`HeadlessWorkflowService` là application service trung tâm cho workflow kiểm thử API.

Tất cả adapter bên ngoài phải gọi service này, không gọi trực tiếp core workflow.

Adapter có thể là:

- CLI
- Telegram bot
- Web chat
- REST API
- Dashboard admin
- Internal SDK

Core workflow gồm các thành phần như:

- `FullWorkflowOrchestrator`
- `TestOrchestrator`
- `ExecutionEngine`
- `Validator`
- report graph
- runtime bridge

Adapter chỉ nên là lớp mỏng, không chứa business workflow logic.

---

## 2. File chính

Application service:

```text
src/api_testing_agent/application/headless_workflow_service.py
```

DTO / contract models:

```text
src/api_testing_agent/application/workflow_service_models.py
```

Unit test:

```text
tests/application/test_headless_workflow_service.py
```

Manual verification CLI:

```text
src/api_testing_agent/manual_test/full_workflow/headless_workflow_cli.py
```

---

## 3. Nguyên tắc kiến trúc

### 3.1. Adapter không được gọi core trực tiếp

Không làm trong adapter:

```python
orchestrator = FullWorkflowOrchestrator(settings)
orchestrator.start_from_text(...)
```

Nên làm:

```python
service = HeadlessWorkflowService(settings)
service.start_workflow(...)
```

Lý do:

- tránh CLI, Telegram, Web, REST mỗi nơi tự gọi core theo một kiểu khác nhau
- tránh business logic bị rải ra adapter
- dễ thay đổi core workflow mà không làm vỡ adapter
- dễ test service contract độc lập

---

### 3.2. Service không expose raw object

Service không trả trực tiếp object nội bộ như:

```text
FullWorkflowResult
WorkflowContextSnapshot
internal graph state
runtime object thô
```

Service chỉ trả DTO ổn định:

```text
WorkflowServiceResponse
WorkflowView
WorkflowSnapshotView
WorkflowArtifactView
WorkflowErrorResponse
```

Lý do:

- adapter không phụ thuộc vào cấu trúc nội bộ của orchestrator
- sau này đổi core vẫn giữ được contract bên ngoài
- dễ mở REST API hoặc Telegram bot hơn

---

### 3.3. Status / Snapshot / Artifacts là read-only

Các method sau chỉ được đọc dữ liệu, không được làm workflow chạy tiếp:

```python
get_workflow_status(...)
get_workflow_snapshot(...)
list_workflow_artifacts(...)
```

Đặc biệt, `get_workflow_status(...)` không được gọi:

```python
continue_with_message(message="status")
```

Lý do:

- `continue_with_message(...)` là một turn hội thoại thật
- nếu dùng nó cho status thì có thể làm thay đổi conversation history
- router có thể ghi thêm decision mới
- workflow state có thể bị mutate ngoài ý muốn

Status phải đọc từ snapshot hiện tại.

---

### 3.4. Không để exception thò ra adapter

Nếu workflow lỗi, service phải trả response chuẩn:

```python
WorkflowServiceResponse(
    ok=False,
    error=WorkflowErrorResponse(...),
)
```

Adapter không nên phải xử lý exception nội bộ như:

```text
ValueError
RuntimeError
KeyError
LangGraph error
LLM error
```

Adapter chỉ cần đọc:

```python
response.ok
response.error.error_code
response.error.error_message
response.error.suggested_next_actions
```

---

## 4. Actor Context

Mọi request có thể gắn metadata người gọi:

```python
WorkflowActorContext(
    actor_id=None,
    session_id=None,
    user_id=None,
    org_id=None,
)
```

Ý nghĩa:

| Field | Ý nghĩa |
|---|---|
| `actor_id` | định danh actor tổng quát, ví dụ Telegram user, API key owner |
| `session_id` | session phía adapter |
| `user_id` | user nội bộ khi có auth system |
| `org_id` | organization / tenant |

Hiện tại các field có thể optional.

Lý do giữ sẵn:

- sau này có auth system sẽ không phải đập lại contract
- dễ audit theo user/org
- dễ giới hạn quyền theo org
- dễ tracking workflow theo actor/session

---

## 5. Request DTO

### 5.1. `StartWorkflowRequest`

Dùng khi bắt đầu workflow mới.

```python
StartWorkflowRequest(
    text="test target img_api_staging module image POST",
    actor_context=WorkflowActorContext(...),
    thread_id=None,
    language_policy=None,
    selected_language=None,
)
```

Field:

| Field | Bắt buộc | Ý nghĩa |
|---|---:|---|
| `text` | Có | input ban đầu của user |
| `actor_context` | Không | metadata người gọi |
| `thread_id` | Không | adapter có thể tự cấp thread id |
| `language_policy` | Không | adaptive / session_lock |
| `selected_language` | Không | ép ngôn ngữ `vi` / `en` nếu cần |

Ví dụ:

```python
response = service.start_workflow(
    StartWorkflowRequest(
        text="hãy test API sinh ảnh ở staging",
        actor_context=WorkflowActorContext(
            actor_id="manual_cli",
            session_id="local_session",
        ),
    )
)
```

---

### 5.2. `ContinueWorkflowRequest`

Dùng khi workflow đã có `thread_id`.

```python
ContinueWorkflowRequest(
    thread_id="...",
    message="approve",
    actor_context=WorkflowActorContext(...),
)
```

Field:

| Field | Bắt buộc | Ý nghĩa |
|---|---:|---|
| `thread_id` | Có | workflow thread hiện tại |
| `message` | Có | message tiếp theo của user |
| `actor_context` | Không | metadata người gọi |

Ví dụ:

```python
response = service.continue_workflow(
    ContinueWorkflowRequest(
        thread_id="thread_abc",
        message="approve",
        actor_context=WorkflowActorContext(actor_id="manual_cli"),
    )
)
```

---

### 5.3. `FinalizeWorkflowRequest`

Dùng để finalize report/workflow bằng semantic API.

```python
FinalizeWorkflowRequest(
    thread_id="...",
    actor_context=WorkflowActorContext(...),
    auto_confirm=True,
    finalize_message="lưu",
    confirmation_message="đồng ý",
)
```

Hiện tại đây là transitional bridge.

Nghĩa là service vẫn gửi message vào orchestrator vì orchestrator chưa có method semantic riêng như:

```python
orchestrator.finalize(thread_id)
```

Khi `auto_confirm=True`, nếu report graph hỏi xác nhận, service sẽ gửi tiếp `confirmation_message`.

---

### 5.4. `CancelWorkflowRequest`

Dùng để cancel workflow bằng semantic API.

```python
CancelWorkflowRequest(
    thread_id="...",
    actor_context=WorkflowActorContext(...),
    auto_confirm=True,
    cancel_message="hủy",
    confirmation_message="đồng ý",
)
```

Hiện tại đây cũng là transitional bridge.

Sau này có thể đổi sang:

```python
orchestrator.cancel(thread_id)
```

mà không cần đổi adapter.

---

### 5.5. `RerunWorkflowRequest`

Dùng để yêu cầu rerun từ phase `report_interaction`.

```python
RerunWorkflowRequest(
    thread_id="...",
    instruction="bỏ YT và chỉ test positive",
    actor_context=WorkflowActorContext(...),
)
```

Nếu `instruction` chưa có từ khóa rerun/chạy lại, service sẽ wrap thành:

```text
chạy lại với yêu cầu sau: <instruction>
```

---

## 6. Response DTO

Mọi method của service đều trả về:

```python
WorkflowServiceResponse
```

Shape:

```python
WorkflowServiceResponse(
    ok=True | False,
    operation="start_workflow",
    actor_context=WorkflowActorContext(...),
    workflow=WorkflowView | None,
    snapshot=WorkflowSnapshotView | None,
    artifacts=list[WorkflowArtifactView],
    error=WorkflowErrorResponse | None,
)
```

Nếu thành công:

```python
response.ok is True
response.workflow is not None
```

Nếu lỗi:

```python
response.ok is False
response.error is not None
```

---

## 7. `WorkflowView`

`WorkflowView` là view chính cho adapter hiển thị với user.

Các field quan trọng:

| Field | Ý nghĩa |
|---|---|
| `workflow_id` | id workflow |
| `thread_id` | id thread/session workflow |
| `phase` | phase hiện tại |
| `current_target` | target hiện tại |
| `assistant_message` | message hiển thị cho user |
| `status_message` | trạng thái ngắn |
| `selected_target` | target đã chọn |
| `candidate_targets` | danh sách target nếu cần user chọn |
| `selection_question` | câu hỏi chọn target |
| `scope_confirmation_question` | câu hỏi xác nhận scope |
| `scope_confirmation_summary` | tóm tắt scope |
| `canonical_command` | command chuẩn hóa |
| `understanding_explanation` | giải thích vì sao hệ thống hiểu như vậy |
| `available_actions` | action adapter có thể expose |
| `needs_user_input` | workflow có đang cần user nhập tiếp không |
| `finalized` | workflow đã finalize chưa |
| `cancelled` | workflow đã cancel chưa |
| `rerun_requested` | có yêu cầu rerun không |
| `rerun_user_text` | text dùng cho rerun |
| `artifacts` | artifact refs |

Adapter thường chỉ cần render:

```python
response.workflow.assistant_message
response.workflow.phase
response.workflow.available_actions
response.workflow.artifacts
```

---

## 8. `WorkflowSnapshotView`

`WorkflowSnapshotView` dùng cho debug/admin/dashboard.

Không nên render toàn bộ snapshot cho end-user bình thường.

Các field quan trọng:

| Field | Ý nghĩa |
|---|---|
| `workflow_id` | id workflow |
| `thread_id` | id thread |
| `current_phase` | phase hiện tại |
| `current_subphase` | subphase nếu có |
| `current_target` | target hiện tại |
| `original_user_text` | input ban đầu |
| `selected_target` | target đã chọn |
| `candidate_targets` | target candidates |
| `canonical_command` | command chuẩn |
| `understanding_explanation` | giải thích understanding |
| `pending_question` | câu hỏi đang chờ user |
| `last_router_decision` | lý do router gần nhất |
| `last_scope_user_message` | message scope gần nhất |
| `artifact_refs` | artifact list |
| `active_review_id` | id review session |
| `active_report_session_id` | id report session |

Manual CLI có thể expose bằng lệnh:

```text
/snapshot
```

---

## 9. Error Contract

Khi lỗi:

```python
WorkflowServiceResponse(
    ok=False,
    error=WorkflowErrorResponse(
        error_code=WorkflowErrorCode.WORKFLOW_NOT_FOUND,
        error_message="Workflow thread `abc` was not found.",
        recoverable=True,
        suggested_next_actions=["start_workflow"],
        details={"thread_id": "abc"},
    ),
)
```

### Error codes chuẩn

| Error code | Ý nghĩa |
|---|---|
| `INVALID_INPUT` | input rỗng hoặc sai shape |
| `WORKFLOW_NOT_FOUND` | không tìm thấy thread |
| `INVALID_PHASE_ACTION` | action không hợp lệ với phase |
| `TARGET_NOT_FOUND` | target không tồn tại |
| `SCOPE_SELECTION_INVALID` | scope selection không hợp lệ |
| `FINALIZE_NOT_ALLOWED` | finalize sai phase |
| `CANCEL_NOT_ALLOWED` | cancel sai phase |
| `RERUN_NOT_ALLOWED` | rerun sai phase |
| `INTERNAL_WORKFLOW_ERROR` | lỗi nội bộ không mong muốn |

REST API sau này có thể map:

| Error code | HTTP status gợi ý |
|---|---:|
| `INVALID_INPUT` | 400 |
| `WORKFLOW_NOT_FOUND` | 404 |
| `INVALID_PHASE_ACTION` | 409 |
| `FINALIZE_NOT_ALLOWED` | 409 |
| `CANCEL_NOT_ALLOWED` | 409 |
| `RERUN_NOT_ALLOWED` | 409 |
| `INTERNAL_WORKFLOW_ERROR` | 500 |

---

## 10. Method Contract

### 10.1. `start_workflow`

```python
service.start_workflow(StartWorkflowRequest(...))
```

Mục tiêu:

- mở workflow mới
- gọi `FullWorkflowOrchestrator.start_from_text(...)`
- trả `WorkflowView`

Có thể trả lỗi:

- `INVALID_INPUT`
- `INTERNAL_WORKFLOW_ERROR`

---

### 10.2. `continue_workflow`

```python
service.continue_workflow(ContinueWorkflowRequest(...))
```

Mục tiêu:

- tiếp tục workflow hiện tại
- dùng cho target selection
- dùng cho scope confirmation
- dùng cho review
- dùng cho report interaction
- gọi `FullWorkflowOrchestrator.continue_with_message(...)`

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`
- `INVALID_PHASE_ACTION`
- `INTERNAL_WORKFLOW_ERROR`

Không cho continue nếu workflow ở terminal phase:

```text
finalized
cancelled
rerun_requested
error
```

---

### 10.3. `get_workflow_status`

```python
service.get_workflow_status(thread_id="...")
```

Mục tiêu:

- đọc trạng thái hiện tại
- không mutate workflow
- không gửi message `"status"` vào orchestrator

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`

---

### 10.4. `get_workflow_snapshot`

```python
service.get_workflow_snapshot(thread_id="...")
```

Mục tiêu:

- trả snapshot view cho debug/admin
- read-only

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`

---

### 10.5. `list_workflow_artifacts`

```python
service.list_workflow_artifacts(thread_id="...")
```

Mục tiêu:

- trả artifact refs
- read-only

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`

---

### 10.6. `finalize_workflow`

```python
service.finalize_workflow(FinalizeWorkflowRequest(...))
```

Mục tiêu:

- finalize report/workflow
- chỉ hợp lệ khi phase là `report_interaction`

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`
- `FINALIZE_NOT_ALLOWED`
- `INVALID_PHASE_ACTION`
- `INTERNAL_WORKFLOW_ERROR`

Transitional behavior:

- hiện tại service gửi `finalize_message`
- nếu report graph hỏi xác nhận, service gửi tiếp `confirmation_message` khi `auto_confirm=True`

---

### 10.7. `cancel_workflow`

```python
service.cancel_workflow(CancelWorkflowRequest(...))
```

Mục tiêu:

- cancel workflow/session
- không cho cancel nếu đã finalized/cancelled

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`
- `INVALID_PHASE_ACTION`
- `INTERNAL_WORKFLOW_ERROR`

Transitional behavior:

- hiện tại service gửi `cancel_message`
- nếu report graph hỏi xác nhận, service gửi tiếp `confirmation_message` khi `auto_confirm=True`

---

### 10.8. `rerun_workflow`

```python
service.rerun_workflow(RerunWorkflowRequest(...))
```

Mục tiêu:

- yêu cầu rerun từ report interaction
- chỉ hợp lệ khi phase là `report_interaction`

Có thể trả lỗi:

- `INVALID_INPUT`
- `WORKFLOW_NOT_FOUND`
- `RERUN_NOT_ALLOWED`
- `INTERNAL_WORKFLOW_ERROR`

Nếu instruction chưa có từ khóa rerun/chạy lại, service sẽ wrap thành:

```text
chạy lại với yêu cầu sau: <instruction>
```

---

## 11. Terminal Phases

Các phase sau được coi là terminal:

```text
finalized
cancelled
rerun_requested
error
```

Khi workflow ở terminal phase:

Không cho:

```python
continue_workflow(...)
```

Vẫn cho:

```python
get_workflow_status(...)
get_workflow_snapshot(...)
list_workflow_artifacts(...)
start_workflow(...)
```

---

## 12. Artifact Contract

Artifact view:

```python
WorkflowArtifactView(
    artifact_type="draft_report_json",
    path="reports/...",
    stage="review",
    storage_backend="filesystem",
)
```

Artifact types hiện tại:

```text
draft_report_json
draft_report_md
execution_report_json
execution_report_md
validation_report_json
validation_report_md
staged_final_report_json
staged_final_report_md
final_report_json
final_report_md
artifact_path_N
```

Stages hiện tại:

```text
review
execution
validation
staged_final
finalized
misc
```

---

## 13. Manual Verification

Chạy unit test:

```bash
poetry run pytest tests\application\test_headless_workflow_service.py -v
```

Chạy manual CLI:

```bash
poetry run python -m api_testing_agent.manual_test.full_workflow.headless_workflow_cli
```

Các lệnh manual CLI:

```text
/status
/snapshot
/artifacts
/finalize
/cancel
/rerun <instruction>
/new
/help
/exit
```

---

## 14. Definition of Done cho Bước 9 bản đầu

Bước 9 bản đầu được coi là xong khi:

- `workflow_service_models.py` là source of truth cho DTO
- `headless_workflow_service.py` không chứa DTO duplicate
- service có đủ method:
  - `start_workflow`
  - `continue_workflow`
  - `get_workflow_status`
  - `get_workflow_snapshot`
  - `cancel_workflow`
  - `finalize_workflow`
  - `rerun_workflow`
  - `list_workflow_artifacts`
- `get_workflow_status` là read-only
- unit test pass
- manual CLI chạy được flow thật
- adapter không gọi trực tiếp orchestrator

---

## 15. Không làm trong Bước 9 bản đầu

Không làm:

- Telegram bot thật
- Web UI
- REST API public/internal
- Celery/Redis
- PostgreSQL migration
- microservice split
- sửa core orchestrator lớn
- sửa execution/validation/report internals
- policy engine đầy đủ

Bước 9 bản đầu chỉ tập trung vào:

```text
headless application service contract
```

---

## 16. Roadmap sau contract này

Sau khi Bước 9 ổn:

1. Manual verify full flow bằng headless CLI.
2. Hardening phase:
   - input hardening
   - transition hardening
   - error handling hardening
   - observability hardening
   - contract hardening
3. Adapter layer:
   - Telegram
   - REST API
   - Web chat
4. Scale/platform:
   - Redis
   - Celery
   - PostgreSQL
   - object storage
   - metrics/tracing