import { Suspense, lazy, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { AlertMessage } from "@/components/alert-message";
import { LoadingOverlay } from "@/components/layout/loading-overlay";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useDialogState } from "@/hooks/use-dialog-state";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { AccountDetail } from "@/features/accounts/components/account-detail";
import { AccountList } from "@/features/accounts/components/account-list";
import { AccountsSkeleton } from "@/features/accounts/components/accounts-skeleton";
import { ImportDialog } from "@/features/accounts/components/import-dialog";
import { ResetCreditConfirmDialog } from "@/features/accounts/components/reset-credit-confirm-dialog";
import { AuthExportDialog } from "@/features/accounts/components/auth-export-dialog";
import {
  useAccounts,
  useAccountUsageResetCredits,
  useLocalOAuthImportFiles,
} from "@/features/accounts/hooks/use-accounts";
import { invalidateAccountRelatedQueries } from "@/features/accounts/query-invalidation";
import { queryClient } from "@/lib/query-client";
import {
  DEFAULT_ACCOUNT_SORT_MODE,
  sortAccountsForDisplay,
  type AccountSortMode,
} from "@/features/accounts/sorting";
import { useOauth } from "@/features/accounts/hooks/use-oauth";
import { useSettings, useUpstreamProxyAdmin } from "@/features/settings/hooks/use-settings";
import { useAccountQuotaDisplayStore } from "@/hooks/use-account-quota-display";
import type { AccountAuthExportResponse, AccountSummary } from "@/features/accounts/schemas";
import { usePermission } from "@/features/auth/hooks/use-auth";
import { MemberSwitchPanel } from "@/features/member-switch/components/member-switch-panel";
import { MemberRotationPanel } from "@/features/member-rotation/components/member-rotation-panel";
import { getErrorMessageOrNull } from "@/utils/errors";

const OauthDialog = lazy(() =>
  import("@/features/accounts/components/oauth-dialog").then((m) => ({
    default: m.OauthDialog,
  })),
);

export function AccountsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [accountSortMode, setAccountSortMode] = useState<AccountSortMode>(DEFAULT_ACCOUNT_SORT_MODE);
  const [oauthAccountId, setOauthAccountId] = useState<string | null>(null);
  const {
    accountsQuery,
    importMutation,
    localImportMutation,
    pauseMutation,
    resumeMutation,
    setAliasMutation,
    probeMutation,
    usageResetMutation,
    limitWarmupMutation,
    updateMutation,
    deleteMutation,
    routingPolicyMutation,
    exportAuthMutation,
  } = useAccounts();
  const { settingsQuery } = useSettings();
  const canWrite = usePermission("accounts:write");
  const blurred = usePrivacyStore((state) => state.blurred);
  // Upstream-proxy administration is an `ops:write` read on the backend; cached
  // data from an earlier admin session must not be rendered either.
  const canReadUpstreamProxy = usePermission("ops:write");
  const { upstreamProxyQuery, accountBindingMutation, testEndpointMutation } = useUpstreamProxyAdmin({
    enabled: canReadUpstreamProxy,
  });
  const oauth = useOauth();

  const importDialog = useDialogState();
  const localOAuthFilesQuery = useLocalOAuthImportFiles(importDialog.open && canWrite);
  const oauthDialog = useDialogState();
  type AccountActionTarget = Pick<AccountSummary, "accountId" | "email" | "displayName">;
  const deleteDialog = useDialogState<AccountActionTarget>();
  type ResetCreditDialogTarget = { accountId: string; availableResetCredits: number };
  const resetCreditDialog = useDialogState<ResetCreditDialogTarget>();
  const usageResetDialog = useDialogState<AccountActionTarget>();
  const exportDialog = useDialogState<AccountAuthExportResponse>();
  const [deleteHistory, setDeleteHistory] = useState(false);

  const accounts = useMemo(
    () => accountsQuery.data ?? [],
    [accountsQuery.data],
  );
  const showResetCreditBadges = settingsQuery.data?.showResetCreditBadges ?? true;
  const showResetCreditExpiryBadge = settingsQuery.data?.showResetCreditExpiryBadge ?? true;
  const quotaDisplay = useAccountQuotaDisplayStore((s) => s.quotaDisplay);
  const sortedAccounts = useMemo(
    () => sortAccountsForDisplay(accounts, quotaDisplay, accountSortMode),
    [accounts, quotaDisplay, accountSortMode],
  );
  const selectedAccountId = searchParams.get("selected");

  const handleSelectAccount = useCallback(
    (accountId: string) => {
      const nextSearchParams = new URLSearchParams(searchParams);
      nextSearchParams.set("selected", accountId);
      setSearchParams(nextSearchParams);
    },
    [searchParams, setSearchParams],
  );

  const resolvedSelectedAccountId = useMemo(() => {
    if (accounts.length === 0) {
      return null;
    }
    if (
      selectedAccountId &&
      accounts.some((account) => account.accountId === selectedAccountId)
    ) {
      return selectedAccountId;
    }
    return sortedAccounts[0]?.accountId ?? null;
  }, [accounts, selectedAccountId, sortedAccounts]);

  const selectedAccount = useMemo(
    () =>
      resolvedSelectedAccountId
        ? (accounts.find(
            (account) => account.accountId === resolvedSelectedAccountId,
          ) ?? null)
        : null,
    [accounts, resolvedSelectedAccountId],
  );
  const resetCreditsQuery = useAccountUsageResetCredits(selectedAccount?.accountId ?? null);

  const mutationBusy =
    importMutation.isPending ||
    localImportMutation.isPending ||
    pauseMutation.isPending ||
    resumeMutation.isPending ||
    setAliasMutation.isPending ||
    probeMutation.isPending ||
    usageResetMutation.isPending ||
    limitWarmupMutation.isPending ||
    deleteMutation.isPending ||
    routingPolicyMutation.isPending ||
    exportAuthMutation.isPending ||
    updateMutation.isPending ||
    accountBindingMutation.isPending ||
    testEndpointMutation.isPending;

  const mutationError =
    getErrorMessageOrNull(importMutation.error) ||
    getErrorMessageOrNull(localImportMutation.error) ||
    getErrorMessageOrNull(pauseMutation.error) ||
    getErrorMessageOrNull(resumeMutation.error) ||
    getErrorMessageOrNull(setAliasMutation.error) ||
    getErrorMessageOrNull(probeMutation.error) ||
    getErrorMessageOrNull(usageResetMutation.error) ||
    getErrorMessageOrNull(limitWarmupMutation.error) ||
    getErrorMessageOrNull(deleteMutation.error) ||
    getErrorMessageOrNull(routingPolicyMutation.error) ||
    getErrorMessageOrNull(exportAuthMutation.error) ||
    getErrorMessageOrNull(updateMutation.error) ||
    getErrorMessageOrNull(settingsQuery.error) ||
    getErrorMessageOrNull(upstreamProxyQuery.error) ||
    getErrorMessageOrNull(accountBindingMutation.error) ||
    getErrorMessageOrNull(testEndpointMutation.error);

  const targetAvailable = (target: AccountActionTarget | null) =>
    !accountsQuery.error && target !== null && accounts.some((account) =>
      account.accountId === target.accountId && account.email === target.email);
  const deleteDisabled = !canWrite || mutationBusy || !targetAvailable(deleteDialog.data);
  const resetDisabled = !canWrite || mutationBusy || !targetAvailable(usageResetDialog.data);

  const handleAuthEnrollmentSettled = (accountId: string | null) => {
    invalidateAccountRelatedQueries(queryClient, accountId ?? undefined);
  };

  return (
    <div className="animate-fade-in-up space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("accounts.page.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("accounts.page.subtitle")}
        </p>
      </div>

      {mutationError ? (
        <AlertMessage variant="error">{mutationError}</AlertMessage>
      ) : null}

      {accountsQuery.error ? (
        <div role="alert" className="space-y-3">
          <AlertMessage variant="error">{getErrorMessageOrNull(accountsQuery.error)}</AlertMessage>
          <Button variant="outline" disabled={accountsQuery.isFetching} onClick={() => void accountsQuery.refetch()}>
            {t("accounts.page.retryLoad")}
          </Button>
        </div>
      ) : null}

      {!accountsQuery.data ? (
        accountsQuery.error ? null : <AccountsSkeleton />
      ) : (
        <div
          data-testid="accounts-layout"
          className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]"
        >
          <div
            data-testid="accounts-list-panel"
            className="min-w-0 min-h-0 self-start"
          >
            <div
              data-testid="accounts-list-card"
              className="flex min-h-0 min-w-0 flex-col rounded-xl border bg-card p-3 sm:p-4"
            >
              <AccountList
                accounts={accounts}
                selectedAccountId={resolvedSelectedAccountId}
                onSelect={handleSelectAccount}
                sortMode={accountSortMode}
                onSortModeChange={setAccountSortMode}
                showResetCreditBadges={showResetCreditBadges}
                onOpenImport={() => importDialog.show()}
                onOpenOauth={() => {
                  setOauthAccountId(null);
                  oauthDialog.show();
                }}
                readOnly={!canWrite}
              />
            </div>
          </div>

          <AccountDetail
            account={selectedAccount}
            showAccountId={selectedAccount?.isEmailDuplicate === true}
            busy={mutationBusy}
            readOnly={!canWrite}
            onPause={(accountId) => void pauseMutation.mutateAsync(accountId)}
            onResume={(accountId) => void resumeMutation.mutateAsync(accountId)}
            onProbe={(accountId) => void probeMutation.mutateAsync({ accountId })}
            onResetUsage={(accountId) => {
              const target = accounts.find((account) => account.accountId === accountId);
              if (canWrite && !mutationBusy && target) {
                usageResetMutation.reset();
                usageResetDialog.show(target);
              }
            }}
            onSetAlias={(accountId, alias) =>
              setAliasMutation.mutateAsync({ accountId, alias })
            }
            onDelete={(accountId) => {
              const target = accounts.find((account) => account.accountId === accountId);
              if (canWrite && !mutationBusy && target) {
                deleteMutation.reset();
                deleteDialog.show(target);
              }
            }}
            onReauth={() => {
              setOauthAccountId(selectedAccount?.accountId ?? null);
              oauthDialog.show();
            }}
            onExportAuth={(accountId) => {
              void exportAuthMutation
                .mutateAsync(accountId)
                .then((result) => exportDialog.show(result))
                .catch(() => null);
            }}
            onResetCredit={(accountId) => {
              const account = accountsQuery.data?.find((item) => item.accountId === accountId);
              resetCreditDialog.show({
                accountId,
                availableResetCredits: account?.availableResetCredits ?? 0,
              });
            }}
            showResetCreditExpiryBadge={showResetCreditExpiryBadge}
            onLimitWarmupChange={(accountId, enabled) =>
              void limitWarmupMutation.mutateAsync({ accountId, enabled })
            }
            onRoutingPolicyChange={(accountId, routingPolicy) =>
              void routingPolicyMutation.mutateAsync({
                accountId,
                routingPolicy,
              })
            }
            onSecurityWorkAuthorizedChange={(accountId, enabled) =>
              void updateMutation.mutateAsync({
                accountId,
                securityWorkAuthorized: enabled,
              })
            }
            upstreamProxyAdmin={canReadUpstreamProxy ? (upstreamProxyQuery.data ?? null) : null}
            onProxyBindingSave={(accountId, payload) =>
              accountBindingMutation.mutateAsync({ accountId, payload })
            }
            onProxyEndpointTest={(endpointId) => testEndpointMutation.mutateAsync(endpointId)}
            resetCredits={resetCreditsQuery.data?.rateLimitResetCredits ?? null}
            resetCreditsLoading={resetCreditsQuery.isFetching}
            resetCreditsUnavailable={!!resetCreditsQuery.error}
          />
        </div>
      )}

      <MemberRotationPanel readOnly={!canWrite} />

      <MemberSwitchPanel readOnly={!canWrite} onAuthEnrollmentSettled={handleAuthEnrollmentSettled} />

      <ImportDialog
        open={importDialog.open}
        busy={importMutation.isPending || localImportMutation.isPending}
        error={
          getErrorMessageOrNull(importMutation.error) ||
          getErrorMessageOrNull(localImportMutation.error) ||
          getErrorMessageOrNull(localOAuthFilesQuery.error)
        }
        localFilesAvailable={localOAuthFilesQuery.data?.available ?? false}
        localFiles={localOAuthFilesQuery.data?.files ?? []}
        localFilesLoading={localOAuthFilesQuery.isLoading}
        onOpenChange={importDialog.onOpenChange}
        onImportLocal={async (filename) => {
          await localImportMutation.mutateAsync(filename);
        }}
        onImport={async (file) => {
          await importMutation.mutateAsync(file);
        }}
      />

      <Suspense fallback={null}>
        <OauthDialog
          open={oauthDialog.open}
          state={oauth.state}
          onOpenChange={(open) => {
            oauthDialog.onOpenChange(open);
            if (!open) {
              setOauthAccountId(null);
            }
          }}
          onStart={async (method) => {
            await oauth.start(method, oauthAccountId ?? undefined);
          }}
          onComplete={async () => {
            await accountsQuery.refetch();
          }}
          onManualCallback={async (callbackUrl) => {
            await oauth.manualCallback(callbackUrl);
          }}
          onReset={oauth.reset}
        />
      </Suspense>

      <AuthExportDialog
        open={exportDialog.open}
        exportData={exportDialog.data}
        onOpenChange={exportDialog.onOpenChange}
      />

      {resetCreditDialog.data ? (
        <ResetCreditConfirmDialog
          open={resetCreditDialog.open}
          accountId={resetCreditDialog.data.accountId}
          summaryAvailableCount={resetCreditDialog.data.availableResetCredits}
          onOpenChange={resetCreditDialog.onOpenChange}
        />
      ) : null}

      <ConfirmDialog
        open={deleteDialog.open}
        title={t("accounts.deleteDialog.title")}
        description={t("accounts.deleteDialog.description")}
        confirmLabel={t("common.actions.delete")}
        cancelLabel={t("common.cancel")}
        keepOpenOnConfirm
        pending={deleteMutation.isPending}
        confirmDisabled={deleteDisabled}
        onOpenChange={(open) => {
          deleteDialog.onOpenChange(open);
          if (!open) setDeleteHistory(false);
        }}
        onConfirm={() => {
          if (deleteDisabled || !deleteDialog.data) {
            return;
          }
          void deleteMutation
            .mutateAsync({ accountId: deleteDialog.data.accountId, deleteHistory })
            .then(() => {
              deleteDialog.hide();
              setDeleteHistory(false);
            })
            .catch(() => { /* The mutation owns the error; preserve this confirmation. */ });
        }}
      >
        {deleteDialog.data ? <div className="min-w-0 space-y-1 text-sm">
          <p className={`break-all ${blurred ? "privacy-blur" : ""}`}>
            {deleteDialog.data.displayName && deleteDialog.data.displayName !== deleteDialog.data.email
              ? `${deleteDialog.data.displayName} · `
              : ""}
            {deleteDialog.data.email}
          </p>
          <code className="block break-all text-xs">{deleteDialog.data.accountId}</code>
        </div> : null}
        {!targetAvailable(deleteDialog.data) || !canWrite ? (
          <p role="alert" className="text-sm text-destructive">{t("common.confirmation.unavailable")}</p>
        ) : null}
        {deleteMutation.error ? <div role="alert">
          <AlertMessage variant="error">{getErrorMessageOrNull(deleteMutation.error)}</AlertMessage>
          <p className="mt-1 text-xs">{t("common.confirmation.failureNotice")}</p>
        </div> : null}
        <div className="flex items-center gap-2">
          <Checkbox
            id="delete-history"
            checked={deleteHistory}
            disabled={deleteMutation.isPending || !canWrite}
            onCheckedChange={(checked) => setDeleteHistory(checked === true)}
          />
          <label
            htmlFor="delete-history"
            className="text-sm text-muted-foreground cursor-pointer"
          >
            {t("accounts.deleteDialog.deleteHistory")}
          </label>
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={usageResetDialog.open}
        title={t("accounts.usageResetDialog.title")}
        description={t("accounts.usageResetDialog.description")}
        confirmLabel={t("common.actions.reset")}
        cancelLabel={t("common.cancel")}
        keepOpenOnConfirm
        pending={usageResetMutation.isPending}
        confirmDisabled={resetDisabled}
        onOpenChange={usageResetDialog.onOpenChange}
        onConfirm={() => {
          if (resetDisabled || !usageResetDialog.data) {
            return;
          }
          void usageResetMutation
            .mutateAsync({ accountId: usageResetDialog.data.accountId })
            .then(() => {
              usageResetDialog.hide();
            })
            .catch(() => { /* Keep the target and redemption identity for explicit retry. */ });
        }}
      >
        {usageResetDialog.data ? <div className="min-w-0 space-y-1 text-sm">
          <p className={`break-all ${blurred ? "privacy-blur" : ""}`}>
            {usageResetDialog.data.displayName && usageResetDialog.data.displayName !== usageResetDialog.data.email
              ? `${usageResetDialog.data.displayName} · `
              : ""}
            {usageResetDialog.data.email}
          </p>
          <code className="block break-all text-xs">{usageResetDialog.data.accountId}</code>
        </div> : null}
        {!targetAvailable(usageResetDialog.data) || !canWrite ? (
          <p role="alert" className="text-sm text-destructive">{t("common.confirmation.unavailable")}</p>
        ) : null}
        {usageResetMutation.error ? <div role="alert">
          <AlertMessage variant="error">{getErrorMessageOrNull(usageResetMutation.error)}</AlertMessage>
          <p className="mt-1 text-xs">{t("common.confirmation.failureNotice")}</p>
        </div> : null}
      </ConfirmDialog>

      <LoadingOverlay
        visible={!!accountsQuery.data && mutationBusy && !deleteDialog.open && !usageResetDialog.open}
        label={t("accounts.page.updating")}
      />
    </div>
  );
}
