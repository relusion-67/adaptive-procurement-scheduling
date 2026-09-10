export function ProcurementRecommendations({ recommendations }) {
  return (
    <section className="staff-panel" aria-label="Operational recommendations">
      <div className="staff-panel__head">
        <div>
          <h2 className="screen__section-title">Operational recommendations</h2>
          <p className="staff-panel__subtitle">
            Deterministic actions derived from the centre insight snapshot.
          </p>
        </div>
      </div>

      <ol className="staff-recommendations">
        {recommendations.map((recommendation) => (
          <li
            key={recommendation.code}
            className={`staff-recommendation staff-recommendation--${recommendation.severity.toLowerCase()}`}
          >
            <div className="staff-recommendation__head">
              <strong>{recommendation.title}</strong>
              <span className="staff-recommendation__priority">
                Priority {recommendation.priority}
              </span>
            </div>
            <p>{recommendation.explanation}</p>
            <ul className="staff-recommendation__evidence">
              {recommendation.evidence.map((evidence) => (
                <li key={evidence}>{evidence}</li>
              ))}
            </ul>
            <code>{recommendation.code}</code>
          </li>
        ))}
      </ol>
    </section>
  );
}
