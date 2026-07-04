# Affected Spec Areas
- Agent tool catalog and default tool behavior
- Agent session lifecycle and persisted artifacts
- Historical query and analytics capabilities
- Terminology and user guidance for output versus data persistence
- Audit and observability expectations for persisted agent artifacts

# New Capabilities
- Agents can query previously saved supplementary data records using filters such as data name, agent type, and session context.
- Agents can query previously saved final outputs using filters such as agent type, session context, and date range.
- Cross-session analysis workflows are enabled by distinct retrieval paths for supplementary data and final outputs.

# Modified Capabilities
- Before: save_result naming implied saved content might be the same as the automatic final output.
- After: save_data explicitly represents optional, agent-initiated supplementary records that can be saved multiple times per session.
- Before: historical retrieval emphasis was centered on execution outcomes without a clear supplementary-data retrieval path.
- After: the platform provides separate retrieval capabilities for supplementary saved data and final outputs.
- Before: output versus intermediate data semantics were frequently interpreted inconsistently.
- After: terminology and behavior clearly differentiate one final output per completed session from zero-or-more supplementary data saves during execution.

# Removed Capabilities
- End-user exposure of the save_result naming in agent tooling and documentation.

# Spec Update Instructions
- Update master documentation references from save_result to save_data where describing agent-initiated persistence.
- Add explicit definitions that distinguish final output from supplementary saved data, including lifecycle timing and expected frequency.
- Document filterable retrieval behavior for supplementary data history and final output history in relevant capability sections.
- Revise user guidance examples to use save_data terminology and preserve the final output concept as a separate artifact.
- Add acceptance-oriented language that validates users can retrieve both supplementary data and final outputs independently.
- Review glossary and onboarding content to ensure consistent terms across product documentation.
