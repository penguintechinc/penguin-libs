"""SPIFFE/SVID peer identity validation."""

from dataclasses import dataclass, field

from penguin_aaa.hardening.validators import validate_spiffe_id


@dataclass(slots=True)
class SPIFFEConfig:
    """Configuration for SPIFFE workload identity validation."""

    trust_domain: str
    workload_socket: str
    allowed_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.trust_domain.strip():
            raise ValueError("trust_domain must not be empty")
        if not self.workload_socket.strip():
            raise ValueError("workload_socket must not be empty")
        for spiffe_id in self.allowed_ids:
            validate_spiffe_id(spiffe_id)


class SPIFFEAuthenticator:
    """
    Validates peer SPIFFE IDs against a configured allowlist.

    In production this is paired with a SPIFFE Workload API client that
    retrieves the peer's SVID from the agent socket.  This class handles
    the identity-comparison logic independently of the transport layer.
    """

    def __init__(self, config: SPIFFEConfig) -> None:
        self._config = config

    def validate_peer_id(self, spiffe_id: str) -> bool:
        """
        Check whether a peer SPIFFE ID is permitted.

        The ID must be a valid spiffe:// URI and must be present in the
        configured allowed_ids list.  An empty allowlist denies all peers.

        Args:
            spiffe_id: The SPIFFE ID asserted by the connecting peer.

        Returns:
            True if the peer is permitted, False otherwise.
        """
        try:
            validate_spiffe_id(spiffe_id)
        except ValueError:
            return False

        if not self._config.allowed_ids:
            return False

        return spiffe_id in self._config.allowed_ids

    def is_same_trust_domain(self, spiffe_id: str) -> bool:
        """
        Check whether a SPIFFE ID belongs to the configured trust domain.

        Args:
            spiffe_id: The SPIFFE ID to inspect.

        Returns:
            True if the ID's trust domain matches the configured trust domain.
        """
        try:
            validate_spiffe_id(spiffe_id)
        except ValueError:
            return False

        # spiffe://trust-domain/path
        without_scheme = spiffe_id[len("spiffe://") :]
        peer_domain = without_scheme.split("/")[0]
        return peer_domain == self._config.trust_domain
