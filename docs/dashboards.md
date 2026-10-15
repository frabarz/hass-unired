# Dashboards

Entity ids derive from account nicknames, e.g. `sensor.core_luz_bill_amount`.
Adjust the examples to your nicknames.

## Amounts at a glance

```yaml
type: entities
title: Cuentas Unired
entities:
  - sensor.core_luz_bill_amount
  - sensor.core_agua_bill_amount
  - sensor.core_internet_bill_amount
```

## Bill detail (markdown)

```yaml
type: markdown
content: >
  {% for bill in state_attr('sensor.core_luz_bill_amount', 'bills') %}
  - **${{ bill.amount }}** · {{ bill.debt_type }}
    (contrato {{ bill.contract }}, vence {{ bill.due_date or 's/f' }})
  {% endfor %}
```

## "Bill prepared" notification

Fires when any bill becomes payable:

```yaml
automation:
  - alias: "Aviso cuenta de luz lista"
    trigger:
      - platform: numeric_state
        entity_id: sensor.core_luz_bill_amount
        above: 0
    action:
      - service: notify.mobile_app_tu_telefono
        data:
          title: "Unired: cuenta lista"
          message: "Luz por ${{ states('sensor.core_luz_bill_amount') }} CLP"
```

Next: [Troubleshooting](troubleshooting.md).
