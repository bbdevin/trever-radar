"""The vendored TPEx intermediate, and the guarantee that verification stays on.

Context: some www.tpex.org.tw nodes send only the leaf certificate, so the
chain cannot be built and the quotes import fails intermittently (2026-09-14:
both the 14:10 and 15:00 rounds, TPEx rows missing from daily_prices). The fix
supplies the missing intermediate from a vendored file. These tests exist so
that (a) the vendored bytes cannot change unnoticed, (b) its expiry surfaces
as a failing test rather than as a silent data gap, and (c) nobody "fixes" a
future chain problem by turning verification off.
"""
import ast
import datetime as dt
import hashlib
from pathlib import Path
import ssl
import unittest

import requests
from requests.utils import DEFAULT_CA_BUNDLE_PATH

import radar.http as radar_http
import radar.tls as tls

RADAR_DIR = Path(tls.__file__).resolve().parent


def _single_cert_info(pem_path) -> dict:
    """The one certificate in `pem_path`, as ssl's dict form (stdlib only).

    `cryptography` is installed transitively but is not a declared dependency
    of this pipeline, so neither the module nor its tests may rely on it.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(pem_path))
    certs = context.get_ca_certs()
    assert len(certs) == 1, f"{pem_path}: expected one certificate, got {len(certs)}"
    return certs[0]


def _common_name(rdns) -> str:
    for rdn in rdns:
        for key, value in rdn:
            if key == "commonName":
                return value
    return ""


class VendoredIntermediateTests(unittest.TestCase):
    """The bytes we ship, pinned by fingerprint and identity."""

    def test_fingerprint_matches_the_pin_in_code_and_in_the_file_header(self):
        digest = hashlib.sha256(tls.pem_der(tls.TWCA_SSL_CA_PEM)).hexdigest()
        self.assertEqual(
            digest, tls.TWCA_SSL_CA_SHA256,
            "the vendored intermediate is not the certificate this code pins. "
            "Replacing it is a reviewable change: verify the new certificate's "
            "signature against a root already in certifi, then update "
            "TWCA_SSL_CA_SHA256 and the .pem header together.",
        )
        # The provenance header must agree with the pin, so the file documents
        # itself correctly rather than carrying a stale fingerprint.
        header = tls.TWCA_SSL_CA_PEM.read_text(encoding="utf-8").split(
            "-----BEGIN CERTIFICATE-----")[0]
        self.assertIn(tls.TWCA_SSL_CA_SHA256, header)
        self.assertIn("sslserver.twca.com.tw/cacert/Cyber_SSL_2023.crt", header)

    def test_it_is_the_ca_that_issued_the_tpex_leaf_and_chains_to_a_certifi_root(self):
        """The whole not-a-downgrade argument, asserted rather than asserted-to.

        Subject must be the issuer named by the www.tpex.org.tw leaf, and its
        own issuer must already be in certifi — meaning anything it vouches
        for was trusted by our existing bundle before this change.
        """
        info = _single_cert_info(tls.TWCA_SSL_CA_PEM)
        self.assertEqual(_common_name(info["subject"]),
                         "TWCA SSL Certification Authority")
        issuer_cn = _common_name(info["issuer"])
        self.assertEqual(issuer_cn, "TWCA CYBER Root CA")

        roots = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        roots.load_verify_locations(cafile=DEFAULT_CA_BUNDLE_PATH)
        root_subjects = {_common_name(c["subject"]) for c in roots.get_ca_certs()}
        self.assertIn(
            issuer_cn, root_subjects,
            f"{issuer_cn} is no longer in certifi's root store; the pinned "
            f"intermediate would then be a new trust anchor rather than a "
            f"missing link, which is a different decision and needs review.",
        )

    def test_expiry_leaves_enough_lead_time_to_replace_it(self):
        """Fail early and loudly instead of months later as a missing-data bug."""
        info = _single_cert_info(tls.TWCA_SSL_CA_PEM)
        not_after = dt.datetime.fromtimestamp(
            ssl.cert_time_to_seconds(info["notAfter"]), dt.timezone.utc)
        days_left = (not_after - dt.datetime.now(dt.timezone.utc)).days
        self.assertGreater(
            days_left, tls.PINNED_CERT_EXPIRY_WARN_DAYS,
            f"the vendored TWCA intermediate expires {not_after:%Y-%m-%d} "
            f"({days_left} days away). Once it expires the TPEx quotes import "
            f"starts failing TLS again and TPEx rows go silently missing from "
            f"daily_prices. Fetch the intermediate named by the current "
            f"www.tpex.org.tw leaf's AIA extension, check its signature "
            f"against a root already in certifi, replace "
            f"{tls.TWCA_SSL_CA_PEM.name} and update TWCA_SSL_CA_SHA256. Do "
            f"not disable verification and do not fetch it at runtime.",
        )

    def test_pem_der_rejects_a_file_holding_more_than_one_certificate(self):
        with self.assertRaisesRegex(ValueError, "exactly one certificate"):
            tls.pem_der(DEFAULT_CA_BUNDLE_PATH)


class SessionTrustConfigurationTests(unittest.TestCase):
    """Where the extra certificate applies, and where it deliberately does not."""

    TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
    TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"

    def test_tpex_requests_use_certifi_plus_the_pinned_intermediate(self):
        adapter = radar_http._session.get_adapter(self.TPEX_URL)
        self.assertIsInstance(adapter, tls.ChainCompletingHTTPAdapter)

        context = adapter.ssl_context_for(True)
        loaded = set(context.get_ca_certs(binary_form=True))
        self.assertIn(tls.pem_der(tls.TWCA_SSL_CA_PEM), loaded,
                      "the pinned intermediate is not in the TPEx trust store")

        # "Combined", not "replaced": certifi's roots must still be there, or
        # the chain would have no anchor to terminate at.
        roots = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        roots.load_verify_locations(cafile=DEFAULT_CA_BUNDLE_PATH)
        certifi_ders = set(roots.get_ca_certs(binary_form=True))
        self.assertTrue(certifi_ders, "certifi bundle unexpectedly empty")
        self.assertTrue(certifi_ders <= loaded,
                        "the TPEx bundle dropped certifi roots instead of adding to them")
        self.assertEqual(loaded - certifi_ders, {tls.pem_der(tls.TWCA_SSL_CA_PEM)},
                         "the TPEx bundle carries certificates beyond the one pinned "
                         "intermediate; widen deliberately, not by accident")

    def test_the_tpex_context_verifies_certificates_and_hostnames(self):
        context = radar_http._session.get_adapter(self.TPEX_URL).ssl_context_for(True)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_the_extra_certificate_is_scoped_to_tpex_and_not_to_every_host(self):
        other = radar_http._session.get_adapter(self.TWSE_URL)
        self.assertIsInstance(other, tls.VerifiedHTTPAdapter)
        self.assertNotIsInstance(other, tls.ChainCompletingHTTPAdapter)

    def test_every_https_host_goes_through_the_verification_guard(self):
        for url in (self.TPEX_URL, self.TWSE_URL, "https://example.test/anything"):
            with self.subTest(url=url):
                self.assertIsInstance(radar_http._session.get_adapter(url),
                                      tls.VerifiedHTTPAdapter)

    def test_verification_cannot_be_switched_off_per_request(self):
        """verify=False must fail before a socket is opened, on any host."""
        for url in (self.TPEX_URL, self.TWSE_URL):
            with self.subTest(url=url):
                with self.assertRaises(tls.TLSVerificationDisabled):
                    radar_http._session.get(url, verify=False, timeout=1)

    def test_an_empty_ca_bundle_setting_is_refused_too(self):
        """`verify=""` keeps cert_reqs=CERT_REQUIRED in the pool key but makes
        requests' own cert_verify downgrade the connection to CERT_NONE. It is
        the shape an operator lands on by exporting REQUESTS_CA_BUNDLE="", so
        the guard has to catch it on that second hook, not just the first."""
        with self.assertRaises(tls.TLSVerificationDisabled):
            radar_http._session.get(self.TPEX_URL, verify="", timeout=1)

    def test_verification_cannot_be_switched_off_session_wide(self):
        session = requests.Session()
        tls.configure_session(session)
        session.verify = False
        try:
            with self.assertRaises(tls.TLSVerificationDisabled):
                session.get(self.TPEX_URL, timeout=1)
        finally:
            session.close()


class NoTrustBypassAnywhereInRadarTests(unittest.TestCase):
    """The regression guard: the tempting bad fix is an env var somewhere.

    Source-level (AST, so comments and prose are not matched) because the
    runtime guard in VerifiedHTTPAdapter cannot see a module that builds its
    own session, its own ssl context, or exports REQUESTS_CA_BUNDLE at import
    time before radar.http is even loaded.
    """

    CA_ENV_VARS = {"REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                   "SSL_CERT_FILE", "SSL_CERT_DIR"}

    @staticmethod
    def _dotted(node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    @staticmethod
    def _is_off(node) -> bool:
        """False/0, and the empty string — requests reads `verify=""` as off too.

        (`_urllib3_request_context` keeps cert_reqs=CERT_REQUIRED for an empty
        string, but `cert_verify` then takes the falsy branch and downgrades the
        connection to CERT_NONE, which is exactly the kind of quiet bypass this
        scan exists to catch.)
        """
        if not isinstance(node, ast.Constant):
            return False
        if isinstance(node.value, str):
            return node.value == ""
        return node.value is False or node.value == 0

    def _scan(self, path: Path) -> list[str]:
        return self._scan_source(path.read_text(encoding="utf-8"),
                                 path.relative_to(RADAR_DIR.parent).as_posix())

    def _scan_source(self, source: str, rel: str) -> list[str]:
        tree = ast.parse(source, filename=rel)
        found: list[str] = []

        def report(node, what):
            found.append(f"{rel}:{node.lineno}: {what}")

        def env_names(node):
            """CA-bundle env var names written by this call or subscript."""
            names = []
            for arg in getattr(node, "args", []):
                if isinstance(arg, ast.Constant) and arg.value in self.CA_ENV_VARS:
                    names.append(arg.value)
                if isinstance(arg, ast.Dict):
                    names += [k.value for k in arg.keys
                              if isinstance(k, ast.Constant) and k.value in self.CA_ENV_VARS]
            return names

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "CERT_NONE":
                report(node, "uses ssl.CERT_NONE")
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in ("verify", "check_hostname") and self._is_off(kw.value):
                        report(node, f"passes {kw.arg}=False")
                if self._dotted(node.func).endswith(
                        ("os.putenv", "environ.setdefault", "environ.update")):
                    for name in env_names(node):
                        report(node, f"sets {name}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    dotted = self._dotted(target)
                    if dotted.split(".")[-1] in ("verify", "check_hostname") \
                            and self._is_off(node.value):
                        report(node, f"assigns {dotted} = {ast.unparse(node.value)}")
                    if isinstance(target, ast.Subscript) \
                            and self._dotted(target.value).endswith("environ") \
                            and isinstance(target.slice, ast.Constant) \
                            and target.slice.value in self.CA_ENV_VARS:
                        report(node, f"sets {target.slice.value}")
        return found

    def test_no_module_disables_verification_or_redirects_the_ca_bundle(self):
        modules = sorted(RADAR_DIR.rglob("*.py"))
        self.assertGreater(len(modules), 10, "radar package not found for scanning")
        violations = [v for path in modules for v in self._scan(path)]
        self.assertEqual(
            violations, [],
            "radar must never disable TLS verification or point the CA bundle "
            "somewhere else. A chain problem is fixed by supplying the missing "
            "certificate (see radar/tls.py), not by trusting less: this "
            "pipeline's numbers feed every figure in the product, so an "
            "unverified fetch is a silent integrity bug where a failed fetch "
            "is at least visible. Offenders: " + "; ".join(violations),
        )

    def test_the_scanner_actually_catches_the_bypasses_it_claims_to(self):
        """A guard nobody has seen fail is a guard nobody should rely on."""
        caught = {
            "requests.get(url, verify=False)": "passes verify=False",
            "requests.get(url, verify=0)": "passes verify=False",
            "requests.get(url, verify='')": "passes verify=False",
            "session.verify = False": "assigns session.verify",
            "session.verify = ''": "assigns session.verify",
            "ssl.SSLContext(check_hostname=False)": "passes check_hostname=False",
            "ctx.check_hostname = False": "assigns ctx.check_hostname",
            "ctx.verify_mode = ssl.CERT_NONE": "uses ssl.CERT_NONE",
            "os.environ['REQUESTS_CA_BUNDLE'] = '/tmp/x.pem'": "sets REQUESTS_CA_BUNDLE",
            "os.environ.setdefault('SSL_CERT_FILE', '/tmp/x.pem')": "sets SSL_CERT_FILE",
            "os.environ.update({'CURL_CA_BUNDLE': ''})": "sets CURL_CA_BUNDLE",
            "os.putenv('SSL_CERT_DIR', '/tmp')": "sets SSL_CERT_DIR",
        }
        for source, expected in caught.items():
            with self.subTest(source=source):
                found = self._scan_source(source, "sample.py")
                self.assertTrue(any(expected in hit for hit in found),
                                f"scanner missed {source!r}; got {found}")

        # ...and does not cry wolf over the legitimate shapes radar uses.
        allowed = [
            "ctx.verify_mode = ssl.CERT_REQUIRED",
            "ctx.check_hostname = True",
            "requests.get(url, verify=True)",
            "requests.get(url, verify=bundle_path)",
            "os.environ['RADAR_DB_URL'] = url",
            "# REQUESTS_CA_BUNDLE is deliberately not set here",
            "'do not set SSL_CERT_FILE'",
        ]
        for source in allowed:
            with self.subTest(source=source):
                self.assertEqual(self._scan_source(source, "sample.py"), [])


if __name__ == "__main__":
    unittest.main()
