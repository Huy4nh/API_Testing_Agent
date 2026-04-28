from api_testing_agent.core.target_candidate_service import TargetCandidateService


def test_single_clear_candidate_can_auto_select():
    service = TargetCandidateService(
        ["cms_local", "hello_world_love", "ngrok_live"]
    )

    candidates = service.find_candidates("hãy test hello_world_love cho tôi")
    selected = service.choose_single_if_confident(candidates)

    assert candidates
    assert selected == "hello_world_love"


def test_multiple_hello_candidates_are_returned():
    service = TargetCandidateService(
        ["hello_work", "hello_work_to", "hello_world"]
    )

    candidates = service.find_candidates("hãy test hello cho tôi")
    names = [item.name for item in candidates]

    assert "hello_work" in names
    assert "hello_work_to" in names
    assert "hello_world" in names
    assert len(names) == 3


def test_parse_user_selection_supports_index_and_name():
    service = TargetCandidateService(
        ["hello_work", "hello_work_to", "hello_world"]
    )
    names = ["hello_work", "hello_work_to", "hello_world"]

    assert service.parse_user_selection("2", names) == "hello_work_to"
    assert service.parse_user_selection("hello_world", names) == "hello_world"