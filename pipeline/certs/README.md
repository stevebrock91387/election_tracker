# Extra CA certificates

Used only by sources whose config names them (`cafile`); `pipeline/fetch.py` adds the file to the
default trust store and turns off partial-chain trust, and refuses a file that contains a
self-signed certificate. So a file here can never be a trust anchor by itself: a chain must still
end at a root in the default store. Only intermediates (including cross-certificates) belong here.

## godaddy-tls-root-r1-cross-g2.pem

- What: "GoDaddy TLS Root CA - R1" cross-signed by "Go Daddy Root Certificate Authority - G2".
- From: https://certs.godaddy.com/repository/gd_tls_root-r1-cross-g2.crt.pem, downloaded 2026-11-24.
- SHA-256: 7B:CB:0F:2F:2D:10:31:A6:AF:8D:61:BA:A8:35:D2:83:5A:3B:8B:CC:26:D9:4A:3B:04:8B:16:55:FB:81:29:8C
- Valid: 2025-09-24 to 2037-12-31.
- Why: Florida's results-file host (flelectionfiles.floridados.gov) chains to the self-signed
  "GoDaddy TLS Root CA - R1" (SHA-256 25:CF:3D:A8:...:71:9F, the same as GoDaddy publishes), which
  the Mozilla, Homebrew and macOS stores don't contain (2026-11-24). With this cross-certificate the
  chain ends at Go Daddy Root G2, which they do contain. Steve approved trusting R1 for that host
  (2026-11-24, "Florida option A"); this is the narrower form: no new root is trusted.
- Remove it once R1 is in the default store.
