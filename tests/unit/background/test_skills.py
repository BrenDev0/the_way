from src.background import use_cases


def test_the_skills_to_follow_head_the_instructions():
    text = use_cases.with_skills("Build the SLS landing page.", ["landing-pages", "persuasive-copy"])

    assert text.startswith("SKILLS TO FOLLOW.")
    assert "- landing-pages\n- persuasive-copy" in text
    assert text.endswith("Build the SLS landing page.")
