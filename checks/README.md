# Vision fallback checks

Run with the solver's installed Python dependencies:

```sh
python -m unittest discover -s checks -v
xvfb-run -a python -m checks.browser_fallback
```

The browser fixture exercises the production v2 retry loop with actual iframe
rendering, screenshots, tile clicks, and token polling. It checks rejected local
classification followed by remote success, local success without remote calls,
direct checkbox success, and bounded remote failure. It contacts no CAPTCHA service.

To exercise the real paid OpenRouter transport on the synthetic red-square grid,
set `OPENROUTER_API_KEY` privately and add `--live-openrouter` to the second command.
Only the first fixture uses that API; the other cases remain deterministic. This
checks integration and request count, not accuracy on real CAPTCHA imagery.
