# Contributing to Music Assistant

Everybody is invited and welcome to contribute to Music Assistant. Even if you are not a developer, perhaps you would like to help with the [documentation](https://music-assistant.io)? If you are a developer and have a music service or speaker that isn't supported by Music Assistant yet, why not spend a couple of hours and help to integrate it?

The process is straight-forward.

 - Fork the relevant Music Assistant repository (e.g. [server](https://github.com/music-assistant/server), [frontend](https://github.com/music-assistant/frontend), or [models](https://github.com/music-assistant/models)).
 - Write the code for your music provider, player provider, metadata provider, or plugin.
 - Ensure tests pass and pre-commit hooks succeed (`pre-commit run --all-files`).
 - Create a Pull Request against the [**dev**](https://github.com/music-assistant/server/tree/dev) branch.

## Two ways to add a provider

Support for a music service, a speaker or anything else can reach users in two ways:

 - **In the community catalog.** You build and maintain the provider in a repository of your own and release it when you want. Users install it from the Marketplace in Music Assistant once they enable the community catalog. It does not have to be of use to everyone, and the project does not review its code. Start from the [provider template](https://github.com/music-assistant/community-provider-template); the [community catalog rules](https://github.com/music-assistant/.github/blob/main/COMMUNITY_CATALOG_RULES.md) say what is accepted.
 - **In the server.** The provider ships with Music Assistant, is installed for every user and is supported by the project. That asks more of it and of you, as described below.

## Adding a provider to the server

A provider that ships with Music Assistant is installed for every user and supported by the project. A new one therefore asks for more than working code:

 - **People ask for it.** Link the feature request or discussion that shows the demand.
 - **It is documented.** A pull request on the [documentation](https://github.com/music-assistant/music-assistant.io/blob/main/CONTRIBUTING.md) comes with it.
 - **It meets the standards.** It follows the [development guide](https://github.com/music-assistant/server/blob/dev/DEVELOPMENT.md) and the [usage policy](https://github.com/music-assistant/.github/blob/main/USAGE_POLICY.md), passes the automated checks and has tests of its own.
 - **You maintain it.** You are listed as its maintainer and keep following up on bug reports and on changes in the service, the device or the server.

A provider whose maintainer no longer follows up may be moved out of the server to the [community catalog](https://github.com/music-assistant/.github/blob/main/COMMUNITY_CATALOG_RULES.md). That is announced first, so that someone can take it over.

## Feature suggestions

If you want to suggest a new feature for Music Assistant (e.g. new music or player providers), please [start a discussion](https://github.com/music-assistant/support/discussions/categories/feature-requests-and-ideas) on GitHub.

## Issue Tracker

If you want to report an issue, please [create an issue](https://github.com/music-assistant/support/issues) on the support repository.

## AI Policy

Music Assistant is an [Open Home Foundation](https://www.openhomefoundation.org/) project and follows the [OHF AI Policy](https://github.com/music-assistant/.github/blob/main/AI_POLICY.md). Please read it before submitting AI-assisted contributions. The TLDR: AI tools are allowed, but a human is responsible and must review and understand every change. Autonomous agents and unreviewed AI output will be rejected.
