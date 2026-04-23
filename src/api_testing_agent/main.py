from api_testing_agent.config import Settings
from api_testing_agent.core.execution_engine import ExecutionEngine
from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.core.openapi_ingestor import OpenApiIngestor
from api_testing_agent.core.target_registry import TargetRegistry
from api_testing_agent.core.testcase_generator import TestCaseGenerator

from api_testing_agent.core.domain_alias_resolver import DomainAliasResolver
from api_testing_agent.core.dynamic_target_resolver import DynamicTargetResolver
from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType as ApiTestType
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter

import json

def _make_runtime_parser(resolver=None):
    """
    Tạo parser đọc từ targets.json thật của project.
    Dùng khi muốn integration test với file runtime thật.
    """
    interpreter = NaturalLanguageInterpreter(
        resolver=resolver if resolver is not None else DomainAliasResolver(),
        target_resolver=DynamicTargetResolver.from_targets_file("./targets.json"),
    )
    return RuleBasedIntentParser(interpreter=interpreter)

import json
from enum import Enum
from dataclasses import is_dataclass, asdict

def to_pretty_obj(obj, _seen=None):
    if _seen is None:
        _seen = set()

    obj_id = id(obj)
    if obj_id in _seen:
        return "<circular_reference>"

    # Kiểu cơ bản
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # Enum
    if isinstance(obj, Enum):
        return obj.value   # hoặc return obj.name nếu bạn thích

    # Dataclass
    if is_dataclass(obj):
        _seen.add(obj_id)
        return {k: to_pretty_obj(v, _seen) for k, v in asdict(obj).items()}

    # Dict
    if isinstance(obj, dict):
        _seen.add(obj_id)
        return {str(k): to_pretty_obj(v, _seen) for k, v in obj.items()}

    # List / Tuple / Set
    if isinstance(obj, (list, tuple, set)):
        _seen.add(obj_id)
        return [to_pretty_obj(x, _seen) for x in obj]

    # Pydantic v2
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        _seen.add(obj_id)
        return to_pretty_obj(obj.model_dump(), _seen)

    # Pydantic v1
    if hasattr(obj, "dict") and callable(obj.dict):
        _seen.add(obj_id)
        return to_pretty_obj(obj.dict(), _seen)

    # Object thường
    if hasattr(obj, "__dict__"):
        _seen.add(obj_id)
        return {
            "__class__": obj.__class__.__name__,
            **{k: to_pretty_obj(v, _seen) for k, v in vars(obj).items()}
        }

    # Fallback
    return str(obj)


def pretty_print(obj):
    print("=" * 180)
    print(json.dumps(to_pretty_obj(obj), indent=4, ensure_ascii=False))
        
def main() -> None:
    settings = Settings()
    registry = TargetRegistry.from_json_file(settings.target_registry_path)
    
    parser = _make_runtime_parser()

    # Dùng path /img thay vì module image vì spec của bạn có path /img rõ ràng
    plan = parser.parse("Ở ngrok tạo ảnh content là example giúp mình")

    # Lấy target đúng theo plan
    if plan.target_name:
        target = registry.get(plan.target_name)
    else:
        target = registry.default()


    ingestor = OpenApiIngestor(timeout_seconds=settings.http_timeout_seconds)
    operations = ingestor.load_for_target(target)

    pretty_print([op for op in operations])
    
    generator = TestCaseGenerator()
    cases = generator.generate(target=target, operations=operations, plan=plan)


    if not cases:
        print("No test cases generated.")
        return
    
    print(f"Generated {len(cases)} cases")

    engine = ExecutionEngine(timeout_seconds=20000.0)
    result = engine.execute(target=target, test_case=cases[0])

    print("=" * 80)
    print("CASE ID:", cases[0].id)
    print("METHOD:", cases[0].operation.method.value.upper())
    print("PATH:", cases[0].operation.path)
    print("STATUS CODE:", result.status_code)
    print("ELAPSED MS:", result.elapsed_ms)
    print("HEADERS:", result.response_headers)
    print("RESPONSE JSON:", result.response_json)
    print("RESPONSE TEXT:", result.response_text)
    print("ERROR:", result.error)


if __name__ == "__main__":
    main()