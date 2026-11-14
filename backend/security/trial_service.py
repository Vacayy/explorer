"""Explicit deployment configuration; no initialization, credentials or fallback."""
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from security.public_documents import PublicDocuments
from security.public_evidence import PublicEvidence
from security.trial_chat import TrialChat
from security.trial_identity import TrialIdentity
from security.trial_quota import TrialPolicy, TrialQuota


def secret_file(name, size):
    path = Path(os.environ[name])
    if not path.is_absolute():
        raise ValueError('Invalid secret file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid not in (0, os.getuid()) or metadata.st_size != size):
            raise ValueError('Invalid secret file')
        value = os.read(fd, size + 1)
        if len(value) != size:
            raise ValueError('Invalid secret file')
        return value
    finally:
        os.close(fd)


@dataclass
class TrialService:
    identity: TrialIdentity
    quota: TrialQuota
    chat: TrialChat

    @classmethod
    def from_environment(cls):
        from security.public_completion import PublicCompletionClient
        identity = TrialIdentity(secret_file('EXPLORER_TRIAL_SECRET_FILE', 32),
            os.environ['EXPLORER_PUBLIC_ORIGIN'],
            tuple(v.strip() for v in os.environ.get('EXPLORER_TRIAL_TRUSTED_PROXIES', '').split(',') if v.strip()))
        policy = TrialPolicy(
            per_network_day_limit=int(os.environ['EXPLORER_TRIAL_NETWORK_DAY_LIMIT']),
            global_day_limit=int(os.environ['EXPLORER_TRIAL_GLOBAL_DAY_LIMIT']),
            max_in_flight=int(os.environ['EXPLORER_TRIAL_MAX_IN_FLIGHT']))
        path = Path(os.environ['EXPLORER_TRIAL_DB'])
        if not path.is_absolute():
            raise ValueError('Invalid trial database')
        quota = TrialQuota(path, policy=policy)
        socket = Path(os.environ['EXPLORER_PUBLIC_CHAT_SOCKET'])
        if not socket.is_absolute() or not stat.S_ISSOCK(socket.lstat().st_mode):
            raise ValueError('Invalid completion socket')
        completion = PublicCompletionClient(socket,
            secret_file('EXPLORER_PUBLIC_CHAT_TOKEN_FILE', 64).decode('ascii'))
        return cls(identity, quota, TrialChat(quota, PublicEvidence(PublicDocuments.from_environment()), completion))
