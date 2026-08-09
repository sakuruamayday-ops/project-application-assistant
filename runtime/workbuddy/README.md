# WorkBuddy Windows host runtime

This directory is the version-controlled source of the Windows behavior Hook
shipped with the WorkBuddy skill suite. The native executable is built from
`windows_hook/`; `windows-hooks.json` is the exact Windows host registration
contract for the `jiaotang-workbuddy-skills` marketplace plugin.

The Windows command deliberately resolves the installed marketplace from
`$HOME/.workbuddy` instead of relying on `CODEBUDDY_PLUGIN_ROOT`. WorkBuddy's
Skill sandbox exposes the latter during inline Skill activation, but the native
Windows plugin lifecycle does not expose it consistently.

When lifecycle prompt events are unavailable, Skill activation may recover the
latest user prompt only from a fresh transcript belonging to the current
WorkBuddy project. The state is labeled `skill_activation_recovery`; it is not
reported as an observed `SessionStart` or `UserPromptSubmit` event.
