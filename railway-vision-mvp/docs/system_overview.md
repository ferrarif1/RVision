# RVision System Overview

RVision is an AI-native visual inspection workspace for railway scenarios.

## What the product can do now
- Start from an AI workspace, understand a goal, and recommend the next workflow.
- Upload image, video, and ZIP dataset assets.
- Run online validation tasks against released models.
- Prepare OCR and state-inspection data for training.
- Submit, approve, release, and audit models and pipelines.
- Review results and export confirmed samples back into training datasets.
- Switch to Expert Console when manual control is required.

## Product operating modes
- AI Workspace: default entry for goal-driven planning and workflow routing.
- AI Workflow pages: upload, train, deploy, results, troubleshoot.
- Expert Console: dashboard, assets, tasks, results, models, pipelines, devices, audit, settings.

## Current boundaries
- Not every page executes LLM actions directly; some flows still use rule-based planning.
- Local LLM and remote API providers are configurable, but provider quality and availability depend on the endpoint.
- Expert Console remains the fallback for precise manual editing and deep operational control.
