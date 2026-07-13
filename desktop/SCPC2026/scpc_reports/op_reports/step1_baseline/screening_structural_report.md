# Screening Structural Report for submission.csv

## Control Distribution
- `amend`: 173
- `ask`: 176
- `hold`: 145
- `proceed`: 206

## Scope Mode Distribution
- `none`: 152
- `raw`: 15
- `redacted`: 217
- `status_only`: 160
- `summary`: 156

## Target Top 30
- `user`: 181
- `memory_store`: 157
- `privacy_review`: 99
- `project_room`: 72
- `legal_review`: 52
- `family_room`: 34
- `vendor_alpha`: 34
- `audit_vendor`: 30
- `clinic_portal`: 15
- `caregiver`: 10
- `fitness_coach`: 7
- `entryway`: 2
- `GalaxyStore`: 2
- `notification_preview`: 1
- `gallery_permission`: 1
- `bedroom`: 1
- `security_review`: 1
- `child_room`: 1

## Policy Requires Confirmation Distribution
- `True`: 226
- `False`: 474

## Plan Sequence Distribution
- `[read -> clarify]`: 176
- `[read -> verify -> update]`: 157
- `[read -> redact -> dispatch]`: 155
- `[guard]`: 145
- `[read -> summarize -> dispatch]`: 55
- `[read -> dispatch]`: 9
- `[read -> verify -> toggle]`: 2
- `[read -> verify -> pay]`: 1

## Diagnostics (not scoring priors)
- Screening labels are unavailable; focal counts below are coverage/integrity, not accuracy.
- **total excluded fields**: 614
- **structurally resolved focal count**: 700 / 700
- **submission/structural focal agreement**: 700 / 700
- **focal method `history_binding`**: 237
- **focal method `marker_trace`**: 463
- **memory_store count**: 157
- **status_only count**: 160
- **redacted count**: 217
- **proceed count**: 206
