"""Run with python -m scripts.seed_half_pizzas against the configured database."""

from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.models import Producto
from gastroflow.services.combo_rules import ensure_half_pizza_rules


def main() -> None:
    with Session(engine) as session:
        rules = ensure_half_pizza_rules(session)
        names = {product.id: product.nombre for product in session.exec(select(Producto)).all()}
        summary = [(names[rule.producto_a_id], names[rule.producto_b_id]) for rule in rules]
        session.commit()
    print(f"{len(summary)} combinaciones registradas con precio PROMEDIO:")
    for first, second in summary:
        print(f"- {first} / {second}")


if __name__ == "__main__":
    main()
