# Task packet template

Use this template when drafting the human-readable version of a task before converting it into JSON.

## Identity

- task_id:
- title:
- role:
- target_repo_name:

## Base

- base_ref:
- worker_branch:

## Goal

Describe the exact outcome required.

## Writable scope

List the only paths the worker may modify.

## Read-only context

List files or directories the worker should read for context.

## Constraints

State the hard constraints explicitly.

## Validation commands

List the commands the worker should run if feasible.

## Deliverables

State what artifacts or code outcomes are expected.

## Acceptance notes

Describe what would make the result acceptable.

## Rejection notes

Describe what would make the result unacceptable.
