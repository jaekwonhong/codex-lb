import { ShieldCheck } from "lucide-react";
import { lazy, Suspense, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { AlertMessage } from "@/components/alert-message";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { LoadingOverlay } from "@/components/layout/loading-overlay";
import { Button } from "@/components/ui/button";
import type {
	ApiKey,
	ApiKeyCreateRequest,
	ApiKeyUpdateRequest,
} from "@/features/api-keys/schemas";
import { ApiKeyCreatedDialog } from "@/features/api-keys/components/api-key-created-dialog";
import { ApiKeysOverview } from "@/features/api-keys/components/api-keys-overview";
import { ApiDetail } from "@/features/apis/components/api-detail";
import { ApiList } from "@/features/apis/components/api-list";
import { ApisSkeleton } from "@/features/apis/components/apis-skeleton";
import {
	useApiKeys,
	useApiKeyTrends,
	useApiKeyUsage7Day,
} from "@/features/apis/hooks/use-apis";
import { useAuthStore, usePermission } from "@/features/auth/hooks/use-auth";
import { useDialogState } from "@/hooks/use-dialog-state";
import { getErrorMessageOrNull } from "@/utils/errors";

const ApiKeyCreateDialog = lazy(() =>
	import("@/features/api-keys/components/api-key-create-dialog").then((m) => ({
		default: m.ApiKeyCreateDialog,
	})),
);
const ApiKeyEditDialog = lazy(() =>
	import("@/features/api-keys/components/api-key-edit-dialog").then((m) => ({
		default: m.ApiKeyEditDialog,
	})),
);

export function ApisPage() {
	const { t } = useTranslation();
	const [searchParams, setSearchParams] = useSearchParams();
	// The backend answers every API-key read with 403 for principals without
	// `api_keys:read`, so the queries stay idle and the page explains instead.
	// Mutations still run behind the coarse write alias, so the controls follow it.
	const canReadKeys = usePermission("api_keys:read");
	const canWrite = useAuthStore((state) => state.canWrite);
	const {
		apiKeysQuery,
		createMutation,
		updateMutation,
		deleteMutation,
		regenerateMutation,
	} = useApiKeys({ enabled: canReadKeys });

	const createDialog = useDialogState();
	const editDialog = useDialogState<ApiKey>();
	const deleteDialog = useDialogState<ApiKey>();
	const createdDialog = useDialogState<string>();

	const apiKeys = useMemo(() => apiKeysQuery.data ?? [], [apiKeysQuery.data]);
	const selectedKeyId = searchParams.get("selected");

	const handleSelectKey = useCallback(
		(keyId: string) => {
			const nextSearchParams = new URLSearchParams(searchParams);
			nextSearchParams.set("selected", keyId);
			setSearchParams(nextSearchParams);
		},
		[searchParams, setSearchParams],
	);

	const resolvedSelectedKeyId = useMemo(() => {
		if (apiKeys.length === 0) return null;
		if (selectedKeyId && apiKeys.some((k) => k.id === selectedKeyId))
			return selectedKeyId;
		return apiKeys[0].id;
	}, [apiKeys, selectedKeyId]);

	const selectedApiKey = useMemo(
		() =>
			resolvedSelectedKeyId
				? (apiKeys.find((k) => k.id === resolvedSelectedKeyId) ?? null)
				: null,
		[apiKeys, resolvedSelectedKeyId],
	);

	const trendsQuery = useApiKeyTrends(selectedApiKey?.id ?? null, { enabled: canReadKeys });
	const usage7DayQuery = useApiKeyUsage7Day(selectedApiKey?.id ?? null, { enabled: canReadKeys });

	const mutationBusy =
		createMutation.isPending ||
		updateMutation.isPending ||
		deleteMutation.isPending ||
		regenerateMutation.isPending;
	const controlsDisabled = mutationBusy || !canWrite;
	const deleteAvailable =
		!apiKeysQuery.error &&
		deleteDialog.data !== null &&
		apiKeys.some((key) => key.id === deleteDialog.data?.id);

	const mutationError =
		getErrorMessageOrNull(createMutation.error) ||
		getErrorMessageOrNull(updateMutation.error) ||
		getErrorMessageOrNull(deleteMutation.error) ||
		getErrorMessageOrNull(regenerateMutation.error);
	const listError = getErrorMessageOrNull(apiKeysQuery.error);
	const usage7DayError = getErrorMessageOrNull(usage7DayQuery.error);
	const pageError = mutationError || (apiKeysQuery.data ? listError : null);

	const handleCreate = async (payload: ApiKeyCreateRequest) => {
		if (controlsDisabled) throw new Error(t("common.confirmation.unavailable"));
		const created = await createMutation.mutateAsync(payload);
		createdDialog.show(created.key);
	};

	const handleUpdate = async (payload: ApiKeyUpdateRequest) => {
		if (controlsDisabled) throw new Error(t("common.confirmation.unavailable"));
		if (!editDialog.data) return;
		await updateMutation.mutateAsync({ keyId: editDialog.data.id, payload });
	};

	if (!canReadKeys) {
		return (
			<div className="animate-fade-in-up space-y-6">
				<div>
					<h1 className="text-2xl font-semibold tracking-tight">{t("apis.page.title")}</h1>
					<p className="mt-1 text-sm text-muted-foreground">
						{t("apis.page.subtitle")}
					</p>
				</div>
				<div
					role="status"
					className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card p-8 text-center"
				>
					<div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
						<ShieldCheck className="h-5 w-5 text-primary" aria-hidden="true" />
					</div>
					<p className="text-sm font-medium">{t("apis.page.adminOnlyTitle")}</p>
					<p className="text-xs text-muted-foreground">{t("apis.page.adminOnlyDescription")}</p>
				</div>
			</div>
		);
	}

	return (
		<div className="animate-fade-in-up space-y-6">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">{t("apis.page.title")}</h1>
				<p className="mt-1 text-sm text-muted-foreground">
					{t("apis.page.subtitle")}
				</p>
			</div>

			{pageError ? (
				<AlertMessage variant="error">{pageError}</AlertMessage>
			) : null}

			{apiKeysQuery.isPending && !apiKeysQuery.data ? (
				<ApisSkeleton />
			) : !apiKeysQuery.data ? (
				<div className="space-y-3 rounded-xl border bg-card p-4">
					<AlertMessage variant="error">
						{listError ?? t("apiKeys.toasts.loadFailed")}
					</AlertMessage>
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={() => {
							void apiKeysQuery.refetch();
						}}
						disabled={apiKeysQuery.isFetching}
					>
						{t("common.actions.retry")}
					</Button>
				</div>
			) : (
				<div className="space-y-6">
					<ApiKeysOverview apiKeys={apiKeys} />

					<div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
						<div className="rounded-xl border bg-card p-4">
							<ApiList
									apiKeys={apiKeys}
									selectedKeyId={resolvedSelectedKeyId}
									onSelect={handleSelectKey}
									onOpenCreate={() => { if (!controlsDisabled) createDialog.show(); }}
									readOnly={!canWrite}
							/>
						</div>

						<ApiDetail
							apiKey={selectedApiKey}
							trends={trendsQuery.data}
							usage7Day={usage7DayQuery.data}
							usage7DayLoading={usage7DayQuery.isPending}
							usage7DayError={usage7DayError}
							busy={mutationBusy}
							readOnly={!canWrite}
								onEdit={(apiKey) => { if (!controlsDisabled) editDialog.show(apiKey); }}
								onToggleActive={(apiKey) => {
									if (controlsDisabled) return;
									void updateMutation
									.mutateAsync({
										keyId: apiKey.id,
										payload: { isActive: !apiKey.isActive },
									})
									.catch(() => null);
							}}
								onDelete={(apiKey) => {
									if (!controlsDisabled) {
										deleteMutation.reset();
										deleteDialog.show(apiKey);
									}
								}}
								onRegenerate={(apiKey) => {
									if (controlsDisabled) return;
									void regenerateMutation
									.mutateAsync(apiKey.id)
									.then((result) => {
										createdDialog.show(result.key);
									})
									.catch(() => null);
							}}
						/>
					</div>
				</div>
			)}

			<Suspense fallback={null}>
				<ApiKeyCreateDialog
					open={createDialog.open}
					busy={createMutation.isPending}
					onOpenChange={createDialog.onOpenChange}
					onSubmit={handleCreate}
				/>

				<ApiKeyEditDialog
					open={editDialog.open}
					busy={updateMutation.isPending}
					apiKey={editDialog.data}
					onOpenChange={editDialog.onOpenChange}
					onSubmit={handleUpdate}
				/>
			</Suspense>

			<ApiKeyCreatedDialog
				open={createdDialog.open}
				apiKey={createdDialog.data}
				onOpenChange={createdDialog.onOpenChange}
			/>

			<ConfirmDialog
				open={deleteDialog.open}
				title={t("apiKeys.deleteDialog.title")}
				description={t("apiKeys.deleteDialog.description")}
					confirmLabel={t("common.actions.delete")}
					keepOpenOnConfirm
					pending={deleteMutation.isPending}
					confirmDisabled={controlsDisabled || !deleteAvailable}
					onOpenChange={deleteDialog.onOpenChange}
					onConfirm={() => {
						if (controlsDisabled || !deleteAvailable || !deleteDialog.data) return;
						void deleteMutation
							.mutateAsync(deleteDialog.data.id)
							.then(() => { deleteDialog.hide(); })
							.catch(() => { /* Preserve target; mutation state owns the error. */ });
					}}
				>
					{deleteDialog.data ? <div className="min-w-0 space-y-1 text-sm">
						<p className="break-all">{deleteDialog.data.name} · {deleteDialog.data.keyPrefix}</p>
						<code className="block break-all text-xs">{deleteDialog.data.id}</code>
					</div> : null}
					{!deleteAvailable || !canWrite ? (
						<p role="alert" className="text-sm text-destructive">{t("common.confirmation.unavailable")}</p>
					) : null}
					{deleteMutation.error ? <div role="alert">
						<AlertMessage variant="error">{getErrorMessageOrNull(deleteMutation.error)}</AlertMessage>
						<p className="mt-1 text-xs">{t("common.confirmation.failureNotice")}</p>
					</div> : null}
				</ConfirmDialog>

				<LoadingOverlay
					visible={!!apiKeysQuery.data && mutationBusy && !deleteDialog.open}
					label={t("apiKeys.page.updating")}
			/>
		</div>
	);
}
