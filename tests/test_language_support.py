from api_testing_agent.tasks.language_support import (
    choose_workflow_language,
    detect_user_language,
)


def test_detect_user_language_vietnamese():
    result = detect_user_language("hãy test chức năng sinh ảnh của img", fallback="en")
    assert result == "vi"


def test_detect_user_language_english():
    result = detect_user_language("please test image generation for img", fallback="vi")
    assert result == "en"


def test_choose_workflow_language_keeps_previous_for_ambiguous_short_input():
    result = choose_workflow_language("2", "en")
    assert result == "en"

    result_2 = choose_workflow_language("local", "vi")
    assert result_2 == "vi"