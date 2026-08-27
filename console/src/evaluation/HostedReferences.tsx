import { useEffect, useState } from "react";
import { providerApi } from "../api";
import type { ProviderReadinessSummary } from "../types";
import { SectionCard } from "./evaluationShared";

interface ProviderCard {
  key: "openai" | "gemini";
  name: string;
  model: string;
  route: string;
  configured: boolean;
  variable: string;
}

function providerCards(readiness: ProviderReadinessSummary | null): ProviderCard[] {
  return [
    {
      key: "openai",
      name: "OpenAI Responses",
      model: readiness?.openai.requested_model ?? "gpt-5.6-sol",
      route: "Responses · stateless · storage disabled",
      configured: readiness?.openai.credential_configured ?? false,
      variable: "OPENAI_API_KEY",
    },
    {
      key: "gemini",
      name: "Gemini Interactions",
      model: readiness?.gemini.requested_model ?? "gemini-3.7-flash",
      route: "Interactions · signed-step replay · storage disabled",
      configured: readiness?.gemini.credential_configured ?? false,
      variable: "GEMINI_API_KEY",
    },
  ];
}

/** Whether each hosted reference has a credential configured; never reads a secret value. */
export function HostedReferences(): JSX.Element {
  const [readiness, setReadiness] = useState<ProviderReadinessSummary | null>(null);

  useEffect(() => {
    let active = true;
    providerApi.readiness()
      .then((loaded) => {
        if (active) setReadiness(loaded);
      })
      .catch(() => {
        if (active) setReadiness(null);
      });
    return () => { active = false; };
  }, []);

  const providers = providerCards(readiness);
  return (
    <SectionCard
      count={providers.length}
      eyebrow="Reference models"
      testId="hosted-reference-readiness"
      title="Hosted references"
    >
      <p className="evaluation-lead">GPT and Gemini are separately labeled hosted references.</p>
      <div className="evaluation-tile-grid">
        {providers.map((provider) => (
          <article className="evaluation-tile" data-testid={`provider-readiness-${provider.key}`} key={provider.key}>
            <div className="evaluation-tile-head">
              <strong>{provider.name}</strong>
              <span className={`evaluation-status ${provider.configured ? "is-completed" : "is-interrupted"}`}>
                {provider.configured ? "Configured" : "Missing credential"}
              </span>
            </div>
            <span>{provider.model}</span>
            <span>{provider.route}</span>
            {!provider.configured && (
              <small>
                Set {provider.variable} only in the launch environment. No secret value is
                read into this view.
              </small>
            )}
          </article>
        ))}
      </div>
    </SectionCard>
  );
}
