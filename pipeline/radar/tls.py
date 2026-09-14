"""Trust configuration for outbound HTTPS: chain completion, scoped per host.

The problem this solves
----------------------
Some nodes behind the TPEx load balancer send only the leaf certificate in the
TLS handshake, omitting the ``TWCA SSL Certification Authority`` intermediate
that issued it.  OpenSSL then cannot build a path from the leaf to any trust
anchor and fails with ``unable to get local issuer certificate``; ``requests``
does not follow the leaf's AIA extension to fetch the missing link.  Because
it is only *some* nodes, the symptom is intermittent: on 2026-09-14 the daily
quotes import failed at 14:10 and again at 15:00 and TPEx rows went missing
from ``daily_prices``, while 09-11 had imported normally.

The fix is to hand OpenSSL the intermediate ourselves, from a vendored file
(``certs/twca_ssl_certification_authority.pem``), and leave verification on.

Why this is not a downgrade
---------------------------
The pinned intermediate is issued by ``TWCA CYBER Root CA``, which is already
in certifi's root store.  Every certificate it can vouch for was therefore
*already* trusted by our existing bundle — on the TPEx nodes that do send a
complete chain, verification succeeds today with no help from us.  Supplying
the intermediate only lets OpenSSL build a path it would otherwise be unable
to complete; it does not introduce a new trust anchor.  Confirmed by
measurement rather than argument: loading the pinned file *without* certifi's
roots still fails the handshake ("unable to get issuer certificate"), because
OpenSSL does not set ``X509_V_FLAG_PARTIAL_CHAIN`` and so still demands a
self-signed root at the top.  The anchor stays ``TWCA CYBER Root CA``.

That is the whole distinction worth holding on to: adding a legitimate
intermediate that chains to an already-trusted root keeps verification intact,
whereas ``verify=False`` would trade a data-availability bug for a data-
integrity one — this pipeline's numbers feed every downstream figure in the
product, and a MITM on the quotes feed is a silent corruption, not an outage.
So there is no flag and no environment-variable escape hatch here, and
:class:`VerifiedHTTPAdapter` actively refuses to make an unverified HTTPS
request even if some future caller asks for one.

Why per host and not one global bundle
--------------------------------------
Widening the trust configuration for *every* outbound request to fix one
misconfigured server is more trust than the problem needs.  ``requests``
selects a transport adapter by longest URL prefix, so the chain-completing
adapter is mounted on ``https://www.tpex.org.tw`` only and every other host
keeps plain certifi.  The per-host scoping costs about ten lines, so the
"single combined bundle" fallback was not needed.

What will break this again
--------------------------
Not the intermediate's expiry alone (2033) but TWCA rotating to a *different*
intermediate, which would look exactly like the original incident.  The
replacement procedure is in the header of the ``.pem`` file.
"""
import os
import ssl
from functools import lru_cache
from pathlib import Path

from requests.adapters import HTTPAdapter
from requests.utils import DEFAULT_CA_BUNDLE_PATH  # certifi, via our declared dep

CERTS_DIR = Path(__file__).resolve().parent / "certs"

# Pinned intermediate.  The fingerprint is the same value recorded in the
# .pem header and is asserted by tests/test_tls_chain.py, so swapping the file
# is a change a reviewer sees rather than something the network can do to us.
TWCA_SSL_CA_PEM = CERTS_DIR / "twca_ssl_certification_authority.pem"
TWCA_SSL_CA_SHA256 = "01af2324d098098f5e0cdf6faabada430b21cce777f47eacb26248b2fda3e531"

# Hosts whose servers do not reliably send a complete chain, mapped to the
# extra certificates needed to complete it.  Keys are matched by requests'
# longest-prefix adapter lookup and must be lowercase.
CHAIN_COMPLETION_HOSTS: dict[str, tuple[Path, ...]] = {
    "www.tpex.org.tw": (TWCA_SSL_CA_PEM,),
}

# How long before a pinned certificate expires the test suite starts failing.
# 180 days is chosen to be longer than one TPEx leaf-certificate lifetime
# (the current leaf runs 2026-09-07..2027-03-24, ~6.5 months), so the alarm
# starts at least one full renewal cycle before anything can break, and long
# enough that a part-time maintainer has several release cycles to fetch the
# replacement, verify it, and deploy.  Shorter (say 30 days) risks the alarm
# and the outage landing in the same week; much longer leaves the suite red
# for years with nothing to do about it.
PINNED_CERT_EXPIRY_WARN_DAYS = 180


class TLSVerificationDisabled(RuntimeError):
    """Raised when something tries to make an HTTPS request without verification.

    Deliberately a hard failure: for a market-data pipeline an unverified fetch
    is worse than a missing fetch, because the missing fetch is visible.
    """


def _is_https(url: str) -> bool:
    return url.lower().startswith("https:")


@lru_cache(maxsize=8)
def _chain_context(base: str | bool, extra_cafiles: tuple[str, ...]) -> ssl.SSLContext:
    """certifi's roots (or the caller's bundle) plus the pinned intermediates.

    Cached because the context object is part of urllib3's connection-pool key:
    returning a fresh one per request would build a new pool every time.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # PROTOCOL_TLS_CLIENT already defaults to these; set them explicitly so
    # that a future edit has to say out loud that it is turning them off.
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    if isinstance(base, str) and os.path.isdir(base):
        context.load_verify_locations(capath=base)
    else:
        context.load_verify_locations(
            cafile=base if isinstance(base, str) else DEFAULT_CA_BUNDLE_PATH)
    for cafile in extra_cafiles:
        context.load_verify_locations(cafile=cafile)
    return context


class VerifiedHTTPAdapter(HTTPAdapter):
    """An adapter that will not make an HTTPS request with verification off.

    ``verify=False`` is forbidden in this codebase; this makes that a property
    of the transport rather than of everyone remembering.  It also catches the
    environment doing it to us (``REQUESTS_CA_BUNDLE=""`` and friends), which
    the source-level regression test cannot see.
    """

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        # Checked before delegating, so a subclass that derives anything from
        # `verify` never sees a value that means "do not verify".  `verify=""`
        # is the one that does not look like it: requests keeps cert_reqs at
        # CERT_REQUIRED for it here and only downgrades later in cert_verify,
        # and it is what an operator gets from `export REQUESTS_CA_BUNDLE=`.
        if _is_https(request.url or "") and not verify:
            self._refuse(request.url, f"verify={verify!r}")
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert)
        if _is_https(request.url or ""):
            self._require_verification(pool_kwargs.get("cert_reqs"), request.url)
        return host_params, pool_kwargs

    def cert_verify(self, conn, url, verify, cert):
        super().cert_verify(conn, url, verify, cert)
        if _is_https(url):
            self._require_verification(conn.cert_reqs, url)

    @classmethod
    def _require_verification(cls, cert_reqs, url: str) -> None:
        if cert_reqs != "CERT_REQUIRED":
            cls._refuse(url, f"cert_reqs={cert_reqs!r}")

    @staticmethod
    def _refuse(url: str, detail: str) -> None:
        raise TLSVerificationDisabled(
            f"refusing to fetch {url} with TLS certificate verification "
            f"disabled ({detail}). Market data feeds every downstream number, "
            f"so an unverified fetch is a silent integrity bug where a failed "
            f"one is at least visible: fix the certificate chain instead — see "
            f"radar/tls.py."
        )


class ChainCompletingHTTPAdapter(VerifiedHTTPAdapter):
    """Verified adapter that also supplies intermediates the server omits.

    The extra certificates are added *alongside* the ordinary root bundle, not
    instead of it, and only for the host this adapter is mounted on.
    """

    # requests pickles adapters by this list; without it a copied session
    # would come back having quietly lost its extra certificates.
    __attrs__ = HTTPAdapter.__attrs__ + ["extra_cafiles"]

    def __init__(self, extra_cafiles, **kwargs):
        self.extra_cafiles = tuple(str(p) for p in extra_cafiles)
        super().__init__(**kwargs)

    def ssl_context_for(self, verify) -> ssl.SSLContext:
        # `verify` is True for every call this codebase makes; a string here
        # means an operator pointed requests at their own bundle (e.g. via
        # REQUESTS_CA_BUNDLE), and honouring it keeps that override meaningful
        # instead of silently discarding it.  A falsy `verify` never reaches
        # this: the base class has already refused the request.
        return _chain_context(verify if isinstance(verify, str) else True,
                              self.extra_cafiles)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert)
        pool_kwargs["ssl_context"] = self.ssl_context_for(verify)
        # The context already carries the bundle these would load, and leaving
        # them set would make urllib3 reload it into the shared context on
        # every new connection.
        pool_kwargs.pop("ca_certs", None)
        pool_kwargs.pop("ca_cert_dir", None)
        return host_params, pool_kwargs

    def cert_verify(self, conn, url, verify, cert):
        super().cert_verify(conn, url, verify, cert)
        conn.ca_certs = None
        conn.ca_cert_dir = None


def configure_session(session) -> None:
    """Mount the verified adapter everywhere and chain completion per host."""
    session.mount("https://", VerifiedHTTPAdapter())
    for host, cafiles in CHAIN_COMPLETION_HOSTS.items():
        session.mount(f"https://{host}", ChainCompletingHTTPAdapter(cafiles))


def pem_der(path) -> bytes:
    """The DER bytes of the single certificate in `path`, ignoring commentary.

    The vendored files carry their provenance as leading ``#`` lines, which
    OpenSSL skips but :func:`ssl.PEM_cert_to_DER_cert` does not.
    """
    text = Path(path).read_text(encoding="utf-8")
    begin, end = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    start = text.index(begin)
    stop = text.index(end, start) + len(end)
    if begin in text[start + len(begin):]:
        raise ValueError(f"{path}: expected exactly one certificate")
    return ssl.PEM_cert_to_DER_cert(text[start:stop] + "\n")
