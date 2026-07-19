"""Closed registrations for the first twenty-one feature artifacts."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureArtifactRegistration:
    """One feature definition bound to its verified historical artifact."""

    name: str
    version: str
    artifact_id: str


def registered_feature_artifacts() -> tuple[FeatureArtifactRegistration, ...]:
    """Return the fixed ordered feature closure used by the first DatasetSpec."""
    values = (
        ("mom_20", "caabbff8de5c733df39f35f5404761bed004d3288451f75d820882c83dbc3fd6"),
        ("mom_60", "95da0f68b63e71675eb7604640351501d07ce111e2dc5d8978306b5c80b1b57c"),
        ("mom_120", "2dad0a3fc639f46fdb4bec53be4da329857cbace7aaa05325dcbc472b661307b"),
        ("reversal_5", "9fefdc76972748084a4ea43941568fa230e2fffe5d9ff5f8e069130e1b28c9ef"),
        ("vol_20", "9ee479f7fabec8cb4e007ca629c9f3a6865226c7c4924ce4a4b974d7d41b349a"),
        ("vol_60", "b01b0f8092fe141c05c823c080b500b654f19a62e797423c4ea7cfa8d9eff614"),
        ("max_drawdown_60", "e5cea4b1191cc88b971ed67e9705f94b0426b97072c59b086341a27e68c0d4ab"),
        ("turnover_mean_20", "20ce7b9420137c53c9e4579648d3eeb93c90ed54d0f0aa05a516886f70360b16"),
        ("amount_median_20", "933eacb3bded0208d822979db3dfa4dd495c9eb810956f35c9fe310ab09f475d"),
        ("amihud_20", "27dc65a0e691d615cc7cca8139baf1841c27e30b3f5ecbc426c07d1d4fdbdaf4"),
        ("log_total_mv", "92b4fd47dfe095080814a5a11edbc883d66d51873aa0b8b0e1260c042fe2bc62"),
        ("earnings_yield_ttm", "e72c64147d7829c7a90e7104025c6a9c628a6efe4e588446a8ccfe0b8be69fb9"),
        ("book_yield", "d3a123ae52913ec7c4c49b9bb793d1fbfc73d88097f43c962328ec95b650b315"),
        ("sales_yield_ttm", "3c0317ac3d3ea47100ee09dbac0e2aa243b57fa8b013cb31d8eee69ff4e79a9f"),
        ("dividend_yield_ttm", "545346fce4bcafc379e2ec559b74fb47efb502465423a3991406845f1f4bf6f8"),
        ("roe", "86f2b99591d19d9a2684bbf9a4783354d353c47cf737ec756f236eee6ce463d5"),
        ("grossprofit_margin", "ac866e63cff57d6184441e1a41edeeb64de88d085ff6d8665dbad6249c7d51ed"),
        ("ocf_to_debt", "4d21cbbf44b5092bf2aea11d44c49e97db64ea30ff0e9d98434552a88a154b92"),
        ("debt_to_assets", "7d9de2fbdc3591ce537082bce4792d0a68c08c1cbd1149f7455197a507677cc7"),
        ("q_sales_yoy", "6540a20c8457f70d8cb4bccda18f455cf1ccceab8ed04b49309c7fff7069d99c"),
        ("q_netprofit_yoy", "fb959366e4ceab00ce239c2b5e54774ab6f1313a0edc1b2dc834061a2f58cc5c"),
    )
    return tuple(
        FeatureArtifactRegistration(name, "1.0.0", f"feature_artifact_{digest}")
        for name, digest in values
    )
