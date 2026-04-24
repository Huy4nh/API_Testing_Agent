# API Testing Agent

Chatbot AI hỗ trợ sinh, thực thi và báo cáo test case cho REST API dựa trên OpenAPI Specification.

## 1. Mô tả dự án

Dự án này xây dựng một prototype chatbot hỗ trợ kiểm thử REST API theo workflow:

Người dùng gửi yêu cầu test qua Telegram  
→ hệ thống phân tích yêu cầu tự nhiên  
→ chuẩn hóa intent  
→ đọc OpenAPI/Swagger  
→ resolve `$ref`  
→ sinh test case  
→ gửi HTTP request thật  
→ kiểm tra response  
→ tạo báo cáo  
→ lưu lịch sử chạy test

## 2. Mục tiêu chính

- Đọc và phân tích OpenAPI/Swagger
- Chuyển yêu cầu tự nhiên thành test plan
- Sinh test case tự động
- Thực thi request thật đến API
- Kiểm tra status code, response schema, required fields
- Tạo báo cáo JSON/Markdown
- Lưu lịch sử test bằng SQLite
- Tích hợp Telegram chatbot

## 3. Kiến trúc hệ thống

Telegram Bot  
→ Orchestrator  
→ Natural Language Interpreter  
→ Dynamic Target Resolver  
→ Domain Alias Resolver  
→ Intent Parser  
→ Target Registry  
→ OpenAPI Ingestor  
→ OpenAPI Ref Resolver  
→ AI Test Case Generator / Test Case Generator  
→ Test Case Normalizer  
→ Execution Engine  
→ Validator  
→ Reporter  
→ SQLite Store

## 4. Các thành phần chính

### `core/nl_interpreter.py`
Xử lý câu chat tự nhiên của người dùng, chuẩn hóa về canonical command trước khi đưa vào parser strict.

### `core/dynamic_target_resolver.py`
Đọc target động từ `targets.json`, tự suy ra target từ tên target, alias hoặc cụm từ người dùng nhập. Không hard-code target trong code.

### `core/domain_alias_resolver.py`
Map các cụm từ nghiệp vụ sang `tag`, `path`, `method` hoặc token trung gian để hỗ trợ nhiều loại API khác nhau mà không làm bẩn parser lõi.

### `core/intent_parser.py`
Parser strict nhận câu lệnh đã được chuẩn hóa và chuyển thành `TestPlan`. Giữ nguyên interface `parse(text) -> TestPlan` để không ảnh hưởng các bước sau.

### `core/target_registry.py`
Đọc và quản lý danh sách API target từ file JSON.

### `core/openapi_ingestor.py`
Đọc OpenAPI từ file hoặc URL, parse `paths`, `parameters`, `requestBody`, `responses`, và phối hợp với ref resolver để tạo `OpenApiOperation`.

### `core/openapi_ref_resolver.py`
Resolve `$ref` nội bộ trong OpenAPI, bao gồm:
- schema `$ref`
- parameter `$ref`
- requestBody `$ref`
- response `$ref`
- nested `$ref` trong `properties`, `items`, `allOf`, `oneOf`, `anyOf`

### `core/schema_faker.py`
Sinh dữ liệu mẫu từ JSON schema. Được dùng để hỗ trợ generator hoặc fallback deterministic khi cần.

### `core/ai_testcase_agent.py`
AI agent dùng LangChain để sinh draft test case có cấu trúc từ `OpenApiOperation` và `TestPlan`.

### `core/ai_testcase_models.py`
Định nghĩa structured output schema cho AI agent khi sinh test case.

### `core/testcase_normalizer.py`
Chuẩn hóa output từ AI agent về `TestCase` chuẩn nội bộ trước khi chuyển sang bước thực thi.

### `core/testcase_generator_ai.py`
Khối sinh test case theo hướng AI-assisted. Chỉ thay thế bước generate testcase, các bước còn lại của pipeline giữ nguyên.

### `core/testcase_generator.py`
Generator rule-based/deterministic dùng làm baseline hoặc fallback. Sinh test case theo 5 nhóm chính:
- positive
- missing required
- invalid type / format
- unauthorized / forbidden
- resource not found

### `core/execution_engine.py`
Gửi HTTP request thật tới API.

### `core/validator.py`
Kiểm tra status code, schema, required fields, nested object, array item, enum, format.

### `core/reporter.py`
Sinh báo cáo JSON và Markdown.

### `db/sqlite_store.py`
Lưu lịch sử test vào SQLite.

### `tasks/orchestrator.py`
Điều phối toàn bộ workflow. Có thể chọn mode sinh test case:
- rule-based
- AI/LangChain

### `bot/telegram_bot.py`
Nhận lệnh từ Telegram và trả kết quả.

## 5. Công nghệ sử dụng

- Python 3.11
- Poetry
- python-telegram-bot
- httpx
- PyYAML
- Pydantic
- SQLite
- LangChain
- Docker
- Pytest

## 6. Cấu trúc thư mục

```text
src/api_testing_agent/
  bot/
  core/
    ai_testcase_agent.py
    ai_testcase_models.py
    domain_alias_resolver.py
    dynamic_target_resolver.py
    intent_parser.py
    nl_interpreter.py
    openapi_ingestor.py
    openapi_ref_resolver.py
    schema_faker.py
    testcase_generator.py
    testcase_generator_ai.py
    testcase_normalizer.py
  tasks/
  db/
tests/
specs/
data/
reports/