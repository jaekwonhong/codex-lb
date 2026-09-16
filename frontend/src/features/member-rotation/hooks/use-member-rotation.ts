import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  getMemberRotationOperatorStatus,
  updateMemberRotationIntent,
} from "@/features/member-rotation/api";
import type { RotationOperatorResponse } from "@/features/member-rotation/schemas";

export const MEMBER_ROTATION_OPERATOR_QUERY_KEY = ["member-rotation", "operator"] as const;

export function useMemberRotationOperator(enabled = true) {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: MEMBER_ROTATION_OPERATOR_QUERY_KEY,
    queryFn: getMemberRotationOperatorStatus,
    enabled,
    refetchInterval: enabled ? 30_000 : false,
    refetchOnWindowFocus: false,
  });
  const intentMutation = useMutation({
    mutationFn: ({
      workspaceId,
      enabled,
      expectedVersion,
    }: {
      workspaceId: string;
      enabled: boolean;
      expectedVersion: number;
    }) => updateMemberRotationIntent(workspaceId, { enabled, expectedVersion }),
    onSuccess: (saved) => {
      queryClient.setQueryData<RotationOperatorResponse>(MEMBER_ROTATION_OPERATOR_QUERY_KEY, (current) => {
        if (!current) return current;
        return {
          ...current,
          workspaces: current.workspaces.map((workspace) =>
            workspace.workspaceId === saved.workspaceId
              ? {
                  ...workspace,
                  automaticRotationEnabled: saved.enabled,
                  controlVersion: saved.version,
                }
              : workspace,
          ),
        };
      });
      toast.success("자동 교체 설정 의도를 저장했습니다.");
      void queryClient.invalidateQueries({ queryKey: MEMBER_ROTATION_OPERATOR_QUERY_KEY });
    },
    onError: (error: Error) => {
      toast.error(error.message || "자동 교체 설정을 저장하지 못했습니다.");
      void queryClient.invalidateQueries({ queryKey: MEMBER_ROTATION_OPERATOR_QUERY_KEY });
    },
  });
  return { statusQuery, intentMutation };
}
