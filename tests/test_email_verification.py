from orderability_engine.email_verification import EmailVerificationStore


def test_verify_with_no_code_requested_fails():
    store = EmailVerificationStore()
    verified, reason = store.verify("student@uni.lu", "123456")
    assert verified is False
    assert reason == "no_code_requested"


def test_issue_then_verify_with_correct_code_succeeds():
    store = EmailVerificationStore()
    store.issue("student@uni.lu", "123456")
    verified, reason = store.verify("student@uni.lu", "123456")
    assert verified is True
    assert reason is None


def test_verify_with_wrong_code_fails_and_can_be_retried():
    store = EmailVerificationStore()
    store.issue("student@uni.lu", "123456")
    verified, reason = store.verify("student@uni.lu", "000000")
    assert verified is False
    assert reason == "incorrect_code"
    # The entry isn't consumed by a wrong guess -- the right code still works after.
    verified, reason = store.verify("student@uni.lu", "123456")
    assert verified is True


def test_verify_consumes_the_code_one_time_use():
    store = EmailVerificationStore()
    store.issue("student@uni.lu", "123456")
    store.verify("student@uni.lu", "123456")
    verified, reason = store.verify("student@uni.lu", "123456")
    assert verified is False
    assert reason == "no_code_requested"


def test_verify_after_expiry_fails():
    store = EmailVerificationStore(code_ttl_seconds=-1)  # already expired the moment it's issued
    store.issue("student@uni.lu", "123456")
    verified, reason = store.verify("student@uni.lu", "123456")
    assert verified is False
    assert reason == "code_expired"


def test_too_many_wrong_attempts_invalidates_the_code():
    store = EmailVerificationStore()
    store.issue("student@uni.lu", "123456")
    for _ in range(5):
        verified, reason = store.verify("student@uni.lu", "wrong0")
        assert verified is False
        assert reason == "incorrect_code"
    # The 6th attempt, even with the CORRECT code, is now locked out.
    verified, reason = store.verify("student@uni.lu", "123456")
    assert verified is False
    assert reason == "too_many_attempts"


def test_different_emails_are_independent():
    store = EmailVerificationStore()
    store.issue("a@uni.lu", "111111")
    store.issue("b@uni.lu", "222222")
    assert store.verify("a@uni.lu", "222222") == (False, "incorrect_code")
    assert store.verify("b@uni.lu", "222222") == (True, None)


def test_issuing_a_new_code_replaces_the_previous_one():
    store = EmailVerificationStore()
    store.issue("student@uni.lu", "111111")
    store.issue("student@uni.lu", "222222")
    assert store.verify("student@uni.lu", "111111") == (False, "incorrect_code")
    assert store.verify("student@uni.lu", "222222") == (True, None)


def test_seconds_until_resend_allowed_is_zero_when_nothing_issued_yet():
    store = EmailVerificationStore()
    assert store.seconds_until_resend_allowed("student@uni.lu") == 0


def test_seconds_until_resend_allowed_is_positive_right_after_issuing():
    store = EmailVerificationStore(resend_cooldown_seconds=60)
    store.issue("student@uni.lu", "123456")
    remaining = store.seconds_until_resend_allowed("student@uni.lu")
    assert 0 < remaining <= 60


def test_seconds_until_resend_allowed_is_zero_once_cooldown_already_elapsed():
    store = EmailVerificationStore(resend_cooldown_seconds=-1)  # already elapsed
    store.issue("student@uni.lu", "123456")
    assert store.seconds_until_resend_allowed("student@uni.lu") == 0
