from api_testing_agent.tasks.operation_catalog_formatter import format_operation_description


def test_format_operation_description_for_image_generate():
    result = format_operation_description(
        method="POST",
        path="/img",
        operation_id="image_generate_img_post",
        summary="Image Generate",
        tags=["image"],
    )
    assert result == "Generate an image from the provided content."


def test_format_operation_description_for_facebook_content():
    result = format_operation_description(
        method="POST",
        path="/FB",
        operation_id="fb_get_content_FB_post",
        summary="Fb Get Content",
        tags=["facebook"],
    )
    assert result == "Retrieve content from Facebook."


def test_format_operation_description_for_youtube_content():
    result = format_operation_description(
        method="POST",
        path="/YT",
        operation_id="yt_get_content_YT_post",
        summary="Yt Get Content",
        tags=["youtube"],
    )
    assert result == "Retrieve content from YouTube."


def test_format_operation_description_for_x_post():
    result = format_operation_description(
        method="POST",
        path="/post/x",
        operation_id="x_post_post_x_post",
        summary="X Post",
        tags=["x"],
    )
    assert result == "Publish a post to X."


def test_format_operation_description_preserves_natural_summary():
    result = format_operation_description(
        method="POST",
        path="/img",
        operation_id="image_generate_img_post",
        summary="Generate image from input content",
        tags=["image"],
    )
    assert result == "Generate image from input content."