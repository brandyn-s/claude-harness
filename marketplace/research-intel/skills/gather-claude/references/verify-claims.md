# Step 13: Verify Claims

**Before presenting any finding to the user**, verify it:

1. **Read the target file** cited in "Baseline ref"
2. **Confirm the cited text actually exists** at approximately the cited
   location
3. **Confirm the "what changed" claim is accurate** — don't conflate
   different files, settings, or features
4. **If two findings reference the same file/setting**, verify they're
   about different things (not the same thing described differently)

If a claim doesn't hold, correct or downgrade the finding before
presenting. Do NOT present unverified findings.

The verification step caught Finding #2 in the first run (conflated
`settings.json` and `~/.claude.json` as the same file). This step
exists because of that near-miss.
