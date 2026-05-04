from api_testing_agent.tasks.workflow_text_localizer import WorkflowTextLocalizer


def build_localizer() -> WorkflowTextLocalizer:
    return WorkflowTextLocalizer(
        model_name="dummy-model",
        model_provider=None,
    )


def test_localizer_translates_selection_question_to_english_with_fallback():
    localizer = build_localizer()

    text = "Bạn muốn test image generation trên môi trường nào? Local, Staging hay Production?"
    result = localizer.localize_text(
        text=text,
        target_language="en",
        text_kind="selection_question",
    )

    assert result == "Which environment would you like to test image generation on? Local, Staging, or Production?"


def test_localizer_translates_understanding_to_english_with_fallback():
    localizer = build_localizer()

    text = "Đã xác định target là 'img_local' và đã match đúng chức năng cụ thể: POST /img."
    result = localizer.localize_text(
        text=text,
        target_language="en",
        text_kind="understanding",
    )

    assert result is not None
    assert "identified the target as 'img_local'" in result.lower()
    assert "matched the intended function: post /img" in result.lower()


def test_localizer_translates_review_preview_keywords_to_english_with_fallback():
    localizer = build_localizer()

    text = """Review round: 1
Understanding: Đã xác định target là 'img_local' và đã match đúng chức năng cụ thể: POST /img.
1. [positive] POST /img với content hợp lệ (URL), prompt và quality tùy chọn
   why: Gửi request hợp lệ với trường required 'content' là URL, kèm prompt và quality để kiểm tra response thành công.
"""
    result = localizer.localize_text(
        text=text,
        target_language="en",
        text_kind="review_preview",
    )

    assert result is not None
    assert "understanding:" in result.lower()
    assert "identified the target as 'img_local'" in result.lower()
    assert "post /img with valid content (url)" in result.lower()
    assert "optional quality" in result.lower()
    assert "identified the target as 'img_local'" in result.lower()