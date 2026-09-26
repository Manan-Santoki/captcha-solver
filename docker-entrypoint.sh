#!/usr/bin/env bash
set -euo pipefail

# Mistral vision keys (reCAPTCHA/hCaptcha image challenges, Aliyun VLM fallback).
# Comma- or newline-separated; written to the file common/mistral.py reads.
if [ -n "${MISTRAL_API_KEYS:-}" ]; then
    printf '%s\n' "$MISTRAL_API_KEYS" | tr ',' '\n' | sed '/^[[:space:]]*$/d' > /app/common/apikey.txt
fi

# Arkose ONNX models live on a volume (~1.4GB). If ARKOSE_MODELS_URL is set, fetch any
# missing model from "$ARKOSE_MODELS_URL/<file>.onnx" once, in the background so the server
# (and its healthcheck) comes up immediately; failures are non-fatal.
if [ -n "${ARKOSE_MODELS_URL:-}" ]; then
    (for f in $(python3 -c "from arkose.predict import _VARIANT_MODELS as m; print(' '.join(sorted(set(m.values()))))"); do
        [ -s "/app/arkose/models/$f" ] && continue
        echo "arkose: downloading $f"
        curl -fsSL --retry 3 -o "/app/arkose/models/$f.part" "${ARKOSE_MODELS_URL%/}/$f" \
            && mv "/app/arkose/models/$f.part" "/app/arkose/models/$f" \
            || { rm -f "/app/arkose/models/$f.part"; echo "arkose: failed to fetch $f"; }
    done; echo "arkose: model sync finished") &
fi

if [ "${BROWSER_HEADLESS:-0}" = "0" ]; then
    exec xvfb-run -a --server-args="-screen 0 1920x1080x24" python3 server.py "$@"
fi
exec python3 server.py "$@"
