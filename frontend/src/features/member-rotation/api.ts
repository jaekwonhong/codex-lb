import { get, put } from "@/lib/api-client";

import {
  RotationIntentUpdateRequestSchema,
  RotationIntentViewSchema,
  RotationOperatorResponseSchema,
  type RotationIntentUpdateRequest,
} from "@/features/member-rotation/schemas";

const BASE_PATH = "/api/member-rotation/operator";

export function getMemberRotationOperatorStatus() {
  return get(BASE_PATH, RotationOperatorResponseSchema);
}

export function updateMemberRotationIntent(
  workspaceId: string,
  payload: RotationIntentUpdateRequest,
) {
  return put(
    `${BASE_PATH}/workspaces/${encodeURIComponent(workspaceId)}/intent`,
    RotationIntentViewSchema,
    { body: RotationIntentUpdateRequestSchema.parse(payload) },
  );
}
