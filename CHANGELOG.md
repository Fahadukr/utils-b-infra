# Changelog

[0.6.0] - 2025-02-18
- Switch the default cache database in MongoDB from the connection string to the database parameter. 
- Switch the default embedding model to 'text-embedding-3-small'. 
- Added support for reasoning modules with the reasoning_effort parameter in the ai.TextGenerator class.

[0.5.0] - 2024-07-30

### updated

- Switch cache mechanism from async to sync

[0.4.0] - 2024-07-20

### Added

- Caching modules

[0.3.0] - 2024-06-27

### Changed

Split the library into main and extra modules, including optional translation utilities.

## [0.2.0] - 2024-06-26:

### Added

- Support for `google-cloud-translate` V3 API.
- Support for OpenAI modules `gpt-4o` and `gpt-4o-2024-05-13` in `ai.calculate_openai_price`

### Fixed

- Issue with json parsing in `ai.TextGenerator.get_ai_response`.

### Changed

- Default openai model to `gpt-4o` in `ai.TextGenerator.get_ai_response`.
- Updated Readme file with more examples.

## [0.1.0] - 2024-06-25 initial release

### Added

- Initial release of the package.
