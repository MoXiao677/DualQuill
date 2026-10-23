"""Version long request limits only on an explicit write."""

def upgrade_long_timeout(state):
    from novel_writer.domain.execution_limits import contains_long_timeout
    if contains_long_timeout(state):
        from novel_writer.application.chapter_lifecycle import upgrade
        upgrade(state)
        state['workspace_version'] = max(state['workspace_version'], 30)
