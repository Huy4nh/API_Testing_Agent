# HANDOFF PACKAGE — API Testing Agent (chuẩn bị sang bước Execution Engine)

## 1. Mục tiêu của handoff này
Tài liệu này dùng để chuyển ngữ cảnh sang một đoạn chat ChatGPT mới để xây tiếp **bước Execution Engine** mà **không làm conflict** với phần đã xây xong.

Chat mới phải đọc kỹ toàn bộ tài liệu này trước khi đề xuất sửa code.

---

## 2. Tình trạng hiện tại của dự án
Dự án đang xây theo hướng:
- chatbot/test agent cho REST API dựa trên OpenAPI
- hỗ trợ multi-target
- nhận yêu cầu test bằng ngôn ngữ tự nhiên
- resolve target
- resolve scope/function
- sinh testcase draft bằng AI
- hỗ trợ review nhiều vòng
- hỗ trợ feedback để thay đổi phạm vi testcase draft

### Hiện đã làm được
1. **Target resolution**
   - nếu có nhiều target gần nhau thì hỏi user chọn
   - nếu target rõ thì đi tiếp

2. **Scope resolution ban đầu**
   - nếu user chỉ rõ chức năng hợp lệ thì test đúng chức năng đó
   - nếu user không chỉ rõ chức năng thì hiểu là test toàn bộ target
   - nếu user chỉ chức năng sai thì báo invalid function + show available functions

3. **AI-first understanding**
   - hướng hiện tại ưu tiên AI để hiểu request/scope/feedback
   - code thường chỉ validate và apply lên OpenAPI thật

4. **Review testcase draft**
   - có vòng review bằng LangGraph
   - có feedback history
   - feedback có thể làm đổi scope testcase ở các vòng sau

5. **Feedback scope refinement**
   - có thể thay scope / thêm scope / bỏ scope / quay lại toàn bộ
   - sau feedback thì preview và active operations đã được cập nhật

6. **Canonical command sync**
   - canonical command hiện đã được sync theo scope mới sau feedback
   - không còn giữ nguyên canonical command cũ khi scope đã đổi

---

## 3. Điều cực kỳ quan trọng: phạm vi hiện tại đã chốt
Chat mới **không được phá** các rule sau:

### Rule A — target
- nếu có nhiều target gần nhau thì vẫn hỏi user chọn
- phần này đang dùng được, không được tự đổi logic lung tung

### Rule B — scope ban đầu
- target rõ + function rõ + hợp lệ -> test đúng function đó
- target rõ + không chỉ rõ function -> test toàn bộ target
- target rõ + function sai -> invalid function + show available functions

### Rule C — feedback trong review
- feedback có thể:
  - thay scope
  - thêm scope
  - bỏ scope
  - reset về all
- feedback phải làm đổi **operation scope thật sự**, không chỉ đổi wording testcase

### Rule D — AI-first
- không quay lại dùng rule-based làm bộ não chính
- AI là lớp hiểu chính
- code chỉ validate/apply/fallback an toàn

---

## 4. Những phần đã xây xong và không nên đập đi làm lại
Chat mới phải **ưu tiên tái sử dụng** những phần này:

### Core understanding / resolution
- `src/api_testing_agent/core/target_resolution_models.py`
- `src/api_testing_agent/core/target_resolution_agent.py`
- `src/api_testing_agent/core/scope_resolution_models.py`
- `src/api_testing_agent/core/scope_resolution_agent.py`
- `src/api_testing_agent/core/feedback_scope_models.py`
- `src/api_testing_agent/core/feedback_scope_agent.py`
- `src/api_testing_agent/core/request_understanding_service.py`

### Review graph + reporter
- `src/api_testing_agent/core/testcase_review_graph.py`
- `src/api_testing_agent/core/reporter/testcase/testcase_reporter.py`

### Orchestrator hiện tại
- `src/api_testing_agent/tasks/orchestrator.py`

### Manual CLI test hiện tại
- `src/api_testing_agent/manual_review_workflow_test.py`

### Test files liên quan AI-first / scope / feedback
- `tests/test_request_understanding_service_ai_first.py`
- `tests/test_feedback_scope_agent_apply.py`
- `tests/test_review_feedback_scope_ai_first.py`
- `tests/test_canonical_command_sync_after_feedback.py`

---

## 5. Những phần chưa làm / đang chuẩn bị làm tiếp
### Bước tiếp theo cần xây
**Execution Engine**

Mục tiêu của bước này:
- nhận testcase draft đã approve
- gửi request HTTP thật tới target API
- tự thêm auth khi phù hợp
- không thêm auth với unauthorized case
- ghi nhận request/response thật
- đo thời gian phản hồi
- tạo execution result để sau này validator/reporter dùng tiếp

### Chưa cần làm ở bước này
- full final reporting branch nếu chưa sẵn sàng
- UI/dashboard
- CI/CD
- performance/load test
- pentest/security nâng cao
- websocket

---

## 6. Yêu cầu rất cụ thể cho bước Execution
Chat mới phải xây bước execution **tương thích hoàn toàn** với những gì đã có.

### Input của execution nên bám vào đâu
Execution phải bám vào testcase draft hiện tại, tức là bám vào các field kiểu:
- target_name
- operation (path, method, parameters, request body, auth_required, responses)
- testcase draft được AI sinh ra
- canonical_command hiện tại
- feedback-adjusted scope hiện tại

### Các nguyên tắc execution đã chốt
1. Dùng request thật tới API thật
2. Có thể dùng `httpx`
3. Nếu operation cần auth:
   - các case bình thường được phép dùng bearer token từ target config
   - riêng unauthorized test thì **cố ý không gắn auth** hoặc gắn auth sai theo policy execution
4. Nếu testcase là not_found:
   - chỉ sửa path param đại diện resource identifier
   - không phá lung tung toàn bộ request
5. Phải ghi log rõ:
   - URL thực tế
   - method
   - headers (an toàn, mask token nếu cần)
   - query params
   - body
   - status code
   - response body
   - response time
   - error nếu có
6. Execution phải là deterministic, không giao cho AI quyết định runtime behavior

---

## 7. Kiến trúc hiện tại mà bước execution phải bám theo
Flow hiện tại về logic là:

User text
-> AI target resolution
-> nếu cần thì user chọn target
-> AI scope resolution
-> sinh understanding result + canonical command
-> build operation contexts
-> AI testcase draft generation
-> review + feedback loop
-> **(bước tiếp theo) execution engine**
-> validator
-> final result report

### Điều rất quan trọng
Execution phải được cắm **sau khi testcase đã được approve**.
Không được nhảy vào execution khi testcase draft còn đang pending review.

---

## 8. Những conflict cần tránh tuyệt đối
Chat mới không được làm các việc sau nếu không thật sự cần:

1. Không rewrite lại target resolution
2. Không rewrite lại scope resolution ban đầu
3. Không bỏ feedback scope refinement
4. Không quay lại kiểu rule-based nặng để hiểu request
5. Không tự đổi format testcase draft hiện tại nếu không tương thích ngược
6. Không đụng `result_report` branch nếu branch đó chưa merge
7. Không phá compatibility của manual review workflow hiện tại

---

## 9. Những file nên tạo / mở rộng cho bước execution
Chat mới nên ưu tiên xây theo hướng tách file rõ ràng, ví dụ:

### Gợi ý file mới
- `src/api_testing_agent/core/execution_models.py`
- `src/api_testing_agent/core/execution_engine.py`
- `src/api_testing_agent/core/auth_header_builder.py`
- `src/api_testing_agent/core/request_runtime_builder.py`
- `src/api_testing_agent/core/execution_log_formatter.py`

### Có thể cập nhật thêm
- `src/api_testing_agent/tasks/orchestrator.py`
- `src/api_testing_agent/manual_review_workflow_test.py`

### Test nên có
- `tests/test_execution_engine.py`
- `tests/test_request_runtime_builder.py`
- `tests/test_auth_header_builder.py`
- `tests/test_execution_flow_after_approval.py`

---

## 10. Contract mong muốn cho execution result
Chat mới nên thiết kế execution result rõ ràng, ví dụ mỗi executed case nên có:
- testcase_id hoặc logical_case_name
- target_name
- operation_id
- method
- path
- final_url
- final_headers
- final_query_params
- final_json_body
- expected_statuses
- actual_status
- response_text hoặc response_json
- response_time_ms
- network_error
- executed_at

Chưa cần chốt validator full ở bước này, nhưng output phải dễ nối sang validator sau đó.

---

## 11. Nội dung nên đưa sang chat mới để nó hiểu ngay
Khi mở chat mới, tôi nên dán theo thứ tự sau:

### (A) Mô tả mục tiêu ngắn gọn
"Tôi đang build API Testing Agent. Tôi đã xong phần target resolution, scope resolution, AI testcase draft review và feedback scope refinement. Bây giờ tôi muốn build bước execution engine tương thích hoàn toàn với phần đã có."

### (B) Dán handoff này
Dán toàn bộ tài liệu handoff này.

### (C) Dán tree thư mục hiện tại
Ví dụ:
```text
src/api_testing_agent/
  core/
    ...
  tasks/
    orchestrator.py
  manual_review_workflow_test.py
tests/
  ...
```

### (D) Dán các file quan trọng hiện tại
Ưu tiên dán nguyên văn các file:
- `src/api_testing_agent/tasks/orchestrator.py`
- `src/api_testing_agent/core/request_understanding_service.py`
- `src/api_testing_agent/core/testcase_review_graph.py`
- `src/api_testing_agent/core/reporter/testcase/testcase_reporter.py`

Nếu chat mới cần chính xác hơn, dán thêm:
- `feedback_scope_agent.py`
- `scope_resolution_agent.py`
- model draft testcase đang dùng

### (E) Dán log chạy thật gần nhất
Ví dụ log manual workflow khi:
- chọn target
- review draft
- feedback đổi scope thành công

### (F) Ra lệnh rất cụ thể cho chat mới
Ví dụ:
"Hãy đọc kỹ toàn bộ handoff và các file tôi dán. Đừng rewrite lại phần target/scope/review. Hãy chỉ xây tiếp bước execution engine theo kiến trúc hiện tại, tách file rõ ràng, có full code copy-paste được, có test, và giải thích chi tiết từng phần."

---

## 12. Prompt mẫu tôi có thể copy sang chat mới
```text
Tôi đang build một dự án API Testing Agent bằng Python.

Hiện tôi đã làm xong các phần sau:
- AI target resolution
- AI scope resolution
- request understanding service
- AI testcase draft generation
- review workflow bằng LangGraph
- feedback scope refinement
- canonical command sync theo scope mới

Tôi KHÔNG muốn bạn rewrite lại các phần trên.
Tôi muốn bạn xây tiếp bước Execution Engine sao cho tương thích hoàn toàn với code hiện tại.

Yêu cầu:
1. Đọc kỹ handoff package và các file tôi gửi.
2. Không phá flow target/scope/review đã có.
3. Chỉ xây tiếp phần execution sau bước approve.
4. Tách file rõ ràng.
5. Có full code copy-paste được.
6. Có test đầy đủ.
7. Giải thích chi tiết từng phần.
8. Nếu cần sửa orchestrator thì chỉ sửa tối thiểu để nối execution vào đúng chỗ.

Bây giờ đây là handoff package và các file hiện tại của tôi:
[PASTE HANDOFF + FILES HERE]
```

---

## 13. Cách giảm conflict tốt nhất
Để chat mới ít conflict nhất, tôi nên làm đúng 3 việc:

### Cách 1 — luôn đưa "source of truth"
Đừng chỉ mô tả bằng lời.
Hãy dán **code thật** của các file lõi.

### Cách 2 — chốt rõ phần nào cấm đụng
Ví dụ:
- không rewrite target resolution
- không rewrite scope resolution
- không đụng result_report branch

### Cách 3 — yêu cầu patch nhỏ thay vì rewrite lớn
Bảo chat mới:
- "hãy xây thêm file mới trước"
- "nếu phải sửa file cũ thì sửa tối thiểu"
- "không được thay đổi public contract hiện tại nếu không thật sự cần"

---

## 14. Nếu muốn an toàn hơn nữa
Tốt nhất trước khi sang chat mới, tôi nên tự chuẩn bị một gói gồm:
- `README trạng thái hiện tại`
- `tree thư mục`
- `4-6 file lõi`
- `1 log chạy thật`
- `1 mô tả rõ bước tiếp theo`

Như vậy chat mới gần như sẽ làm việc như một developer mới join vào đúng project hiện tại.

---

## 15. Kết luận ngắn
Muốn chat mới hiểu đúng và build tiếp không conflict thì phải chuyển cho nó **hệ thống hiện tại dưới dạng contract + source code thật**, không chỉ mô tả bằng lời.

Cốt lõi là:
- nói rõ đã làm được gì
- nói rõ chưa làm gì
- nói rõ file nào là source of truth
- nói rõ phần nào không được phá
- dán code thật của các file lõi
- yêu cầu chat mới chỉ xây tiếp bước execution theo kiến trúc hiện tại

