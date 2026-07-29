# Template for .bob/features/<feature-name>.feature — written by the Specifier.
# Every scenario carries a stable id tag (@S<slice>-AS<n>, or @US<n>-AS<n> in
# yamlkit integration mode). Ids are permanent once approved: tests trace to them.
#
# Test traceability conventions per stack (used when no BDD framework is configured):
#   C#:         [Trait("scenario", "S1-AS1")]
#   TS/JS:      describe('@S1-AS1', ...) or test name containing '@S1-AS1'
#   Python:     @pytest.mark.scenario("S1-AS1") or the id in the test name
#   Java:       @Tag("S1-AS1")
#
# Each scenario is followed by its QA procedure as a comment block: the literal,
# executable steps the QA role runs against the real code.

Feature: <feature title>
  <one-paragraph intent: who needs this and why>

  @S1-AS1
  Scenario: <observable behavior, no implementation details>
    Given <precondition in concrete terms>
    When <action>
    Then <observable, checkable outcome>

  # QA procedure @S1-AS1:
  #   1. <exact command to run / input to provide>
  #   2. <what output/state to check, with the expected literal value>

  @S1-AS2
  Scenario: <edge case: empty input / boundary / error state>
    Given <...>
    When <...>
    Then <...>

  # QA procedure @S1-AS2:
  #   1. <...>
