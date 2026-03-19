# RVision Workflows

## Upload workflow
Use when the user has not provided usable assets yet.
- Collect image, video, or ZIP dataset.
- Confirm purpose: inference, training, finetune, validation.
- After upload, route to validation or training.

## Train workflow
Use when no suitable released model is available or model quality is insufficient.
- Prepare or review data.
- Export train/validation bundle.
- Create training job.
- Return to model approval or validation after training succeeds.

## Deploy workflow
Use when a model has reached approval or release preparation.
- Open model center or pipeline center.
- Check approval status, release scope, and device coverage.
- Continue to devices or audit if required.

## Results workflow
Use when a task has already been created or validation is the next step.
- Query task results.
- Review low-confidence output.
- Export confirmed samples back into training datasets if needed.

## Troubleshoot workflow
Use when the task is blocked by model availability, device state, or failed jobs.
- Inspect task, training, device, and audit clues.
- Identify the blocking stage.
- Return to main workflow after the blocker is removed.
