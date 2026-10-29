import pytest
import encoder_native


def test_unsupported_native_host_is_rejected_before_build_or_driver_probing(monkeypatch):
    monkeypatch.setattr(encoder_native.platform, 'system', lambda: 'Windows')
    with pytest.raises(RuntimeError, match='POSIX macOS/Linux'):
        encoder_native.environment()
