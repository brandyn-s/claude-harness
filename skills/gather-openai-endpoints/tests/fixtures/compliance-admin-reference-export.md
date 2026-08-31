{
 "openapi": "3.0.2",
 "info": {
  "title": "OpenAI Programmatic Admin Platform",
  "version": "2.5.12"
 },
 "paths": {
  "/manage/workspaces/{workspace_id}/usage_limits/workspace": [
   "get",
   "patch"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/groups": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/groups/{group_id}": [
   "get",
   "patch"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/users": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/users/{user_id}": [
   "get",
   "patch"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/users/{user_id}/monthly-usage": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/requests": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/usage_limits/requests/{request_id}": [
   "patch"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/conversations/{conversation_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/conversations/{conversation_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/gpts": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/gpts/{gpt_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/agents": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/agents/{agent_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/agents/{agent_id}/unpublish": [
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/custom_agents/{agent_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/custom_agents/{agent_id}/unpublish": [
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/gpts/{gpt_id}/configs": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/gpt_files/{file_id}": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/gpts/{gpt_id}/files/{file_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/gpts/{gpt_id}/shared_users": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/skills": [
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/agent-skills": [
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/skills/{skill_id}/export": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/skills/{skill_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/users": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/invites": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/invites": [
   "get",
   "post"
  ],
  "/manage/workspaces/{workspace_id}/invites/{invite_id}": [
   "delete",
   "get"
  ],
  "/manage/workspaces/{workspace_id}/invites/{invite_id}/resend": [
   "post"
  ],
  "/manage/workspaces/{workspace_id}/users/{user_id}": [
   "delete",
   "get",
   "post"
  ],
  "/manage/workspaces/{workspace_id}/groups": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/groups/{group_id}": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/groups/{group_id}/users": [
   "get",
   "post"
  ],
  "/manage/workspaces/{workspace_id}/users/{user_id}/groups": [
   "get"
  ],
  "/manage/workspaces/{workspace_id}/groups/{group_id}/users/{user_id}": [
   "delete"
  ],
  "/manage/workspaces/{workspace_id}/service-accounts": [
   "get",
   "post"
  ],
  "/manage/workspaces/{workspace_id}/service-accounts/{service_account_id}": [
   "delete",
   "get",
   "patch"
  ],
  "/manage/workspaces/{workspace_id}/service-accounts/{service_account_id}/credentials": [
   "get",
   "post"
  ],
  "/manage/workspaces/{workspace_id}/service-accounts/{service_account_id}/credentials/{credential_id}": [
   "delete"
  ],
  "/manage/workspaces/{workspace_id}/service-accounts/{service_account_id}/share": [
   "delete",
   "get",
   "patch",
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/files/{file_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/library_files": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/library_files/{library_file_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/pets": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/pets/{pet_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/shared_pets": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/shared_pets/{shared_pet_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/memories": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/memories": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/memories/about_you/summary": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/memory/delete_and_disable": [
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/memory/delete_and_disable": [
   "post"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/memory_contexts/{memory_context_id}/memories/{memory_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/canvases": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/canvas/{textdoc_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/projects": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/projects/{project_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/projects/{project_id}/configs": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/project_files/{file_id}": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/projects/{project_id}/files/{file_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/projects/{project_id}/connector_scopes/{scope_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/projects/{project_id}/shared_users": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/automations": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/recordings": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/recordings/{recording_id}/transcript": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/recordings/{recording_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/automations/{automation_id}": [
   "delete"
  ],
  "/compliance/workspaces/{workspace_id}/codex_tasks/{task_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/codex_environments/{environment_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/codex_environments": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/codex_tasks": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/plugins": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/plugins/{plugin_id}": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/remote_control/environments": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/remote_control/environments/{environment_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/remote_control/environments/{environment_id}/threads": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/remote_control/environments/{environment_id}/threads/{remote_thread_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/remote_control/clients": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/users/{user_id}/remote_control/clients/{client_id}": [
   "delete",
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/logs": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/max_event_time": [
   "get"
  ],
  "/compliance/workspaces/{workspace_id}/logs/{log_file_id}": [
   "get"
  ],
  "/compliance/organizations/{organization_id}/logs": [
   "get"
  ],
  "/compliance/organizations/{organization_id}/max_event_time": [
   "get"
  ],
  "/compliance/organizations/{organization_id}/logs/{log_file_id}": [
   "get"
  ],
  "/analytics/codex/workspaces/{workspace_id}/usage": [
   "get"
  ],
  "/analytics/codex/workspaces/{workspace_id}/code_reviews": [
   "get"
  ],
  "/analytics/codex/workspaces/{workspace_id}/code_review_responses": [
   "get"
  ]
 },
 "x-enum-inventory": [
  [
   "CONVERSATION_MESSAGE",
   "AUDIT_LOG",
   "etc..."
  ],
  [
   "APP_LOG",
   "APP_AUTH_LOG",
   "COSTS",
   "etc..."
  ],
  [
   "CONVERSATION_MESSAGE",
   "AUDIT_LOG",
   "APP_LOG",
   "APP_AUTH_LOG",
   "COSTS",
   "etc..."
  ],
  [
   "WORKSPACE"
  ],
  [
   "LISTED",
   "UNLISTED",
   "PRIVATE"
  ],
  [
   "CODEX_CLI",
   "CODEX_WEB",
   "CODEX_CHROME_EXTENSION_SIDE_PANEL",
   "CODEX_DESKTOP_APP",
   "CODEX_CHATGPT_DESKTOP",
   "CODEX_CLOUD_GENERAL_AGENT",
   "CODEX_ATLAS",
   "CODEX_FLORA",
   "CODEX_WORK_WEB",
   "CODEX_WORK_MOBILE",
   "CODEX_WORK_DESKTOP",
   "CODEX_IDE_VSCODE",
   "CODEX_SLACK",
   "CODEX_GITHUB",
   "CODEX_GITHUB_ACTION",
   "CODEX_SDK_TS",
   "CODEX_SERVICE_EXEC",
   "CODEX_IDE_XCODE",
   "CODEX_IDE_JETBRAINS_INTELLIJ_IDEA",
   "CODEX_IDE_JETBRAINS_INTELLIJ_IDEA_COMMUNITY_EDITION",
   "CODEX_IDE_JETBRAINS_INTELLIJ_IDEA_EDUCATIONAL_EDITION",
   "CODEX_IDE_JETBRAINS_RUBYMINE",
   "CODEX_IDE_JETBRAINS_PYCHARM",
   "CODEX_IDE_JETBRAINS_PYCHARM_COMMUNITY_EDITION",
   "CODEX_IDE_JETBRAINS_DATASPELL",
   "CODEX_IDE_JETBRAINS_PYCHARM_EDUCATIONAL_EDITION",
   "CODEX_IDE_JETBRAINS_PHPSTORM",
   "CODEX_IDE_JETBRAINS_WEBSTORM",
   "CODEX_IDE_JETBRAINS_APPCODE",
   "CODEX_IDE_JETBRAINS_CLION",
   "CODEX_IDE_JETBRAINS_DATAGRIP",
   "CODEX_IDE_JETBRAINS_RIDER",
   "CODEX_IDE_JETBRAINS_GOLAND",
   "CODEX_IDE_JETBRAINS_ANDROID_STUDIO",
   "CODEX_IDE_JETBRAINS_CLIENT",
   "CODEX_IDE_JETBRAINS_GATEWAY",
   "CODEX_IDE_JETBRAINS_FLEET_BACKEND",
   "CODEX_IDE_JETBRAINS_AQUA",
   "CODEX_IDE_JETBRAINS_RUSTROVER",
   "CODEX_IDE_JETBRAINS_WRITERSIDE",
   "CODEX_IDE_JETBRAINS_GITCLIENT",
   "CODEX_IDE_JETBRAINS_MPS",
   "CODEX_UNKNOWN_DEFAULT"
  ]
 ]
}
