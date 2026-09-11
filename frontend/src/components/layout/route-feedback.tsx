import { Component, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export function RouteLoading() {
  const { t } = useTranslation();
  return <p role="status" className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
    <Spinner size="sm" />{t("route.loading")}
  </p>;
}

export function RouteNotFound() {
  const { t } = useTranslation();
  return <section className="rounded-xl border p-6">
    <h1 className="text-lg font-semibold">{t("route.notFound")}</h1>
    <p className="mt-2 text-sm text-muted-foreground">{t("route.notFoundDescription")}</p>
    <Link className="mt-4 inline-block underline" to="/dashboard">{t("route.dashboard")}</Link>
  </section>;
}

function RouteFailure() {
  const { t } = useTranslation();
  return <section role="alert" className="rounded-xl border p-6">
    <h1 className="text-lg font-semibold">{t("route.failed")}</h1>
    <p className="mt-2 text-sm text-muted-foreground">{t("route.failedDescription")}</p>
    <Button className="mt-4" variant="outline" onClick={() => window.location.reload()}>{t("route.reload")}</Button>
  </section>;
}

export class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <RouteFailure /> : this.props.children; }
}
