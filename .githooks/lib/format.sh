# shellcheck shell=bash
#
# Commit subject format, shared by the commit-msg hook and the CI check so the two
# cannot drift apart. Sourced rather than executed, hence the shell directive above
# in place of a shebang.

commit_msg_type_regex='build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test'
commit_msg_scope_regex='.{1,20}'
commit_msg_description_regex='.{1,100}'
commit_msg_regex="^(${commit_msg_type_regex})(\(${commit_msg_scope_regex}\))?: (${commit_msg_description_regex})\$"

# Messages git and the GitHub merge button write for us. Not ours to format.
merge_msg_regex="^(Merge (branch|pull request|remote-tracking branch) .+|Revert \".+\")\$"

# The format proper, with no exemption. Use it for a subject a human wrote and can
# still edit, such as a pull request title.
#
# Usage: subject_is_conventional "<subject line>"
subject_is_conventional() {
  local subject="$1"

  if [[ "$subject" =~ $commit_msg_regex ]]; then
    return 0
  fi

  return 1
}

# The format, plus the messages git and the merge button write on our behalf. Use it
# for commits already in history, which nobody can reword without a rewrite.
#
# Usage: subject_is_valid "<subject line>"
subject_is_valid() {
  local subject="$1"

  if subject_is_conventional "$subject" || [[ "$subject" =~ $merge_msg_regex ]]; then
    return 0
  fi

  return 1
}

commit_msg_help() {
  echo "Commit subjects must read:  <type>(<optional scope>): <description>"
  echo
  echo "  type         one of: ${commit_msg_type_regex//|/, }"
  echo "  scope        optional, 1-20 characters in parentheses"
  echo "  description  1-100 characters"
  echo
  echo "For example:  fix(stats): populate the podman stats fixture through the reconciler"

  return 0
}
