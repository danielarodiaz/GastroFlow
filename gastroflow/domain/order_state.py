from gastroflow.domain.enums import EstadoPedido
from gastroflow.domain.errors import ValidationError

VALID_ORDER_TRANSITIONS: dict[EstadoPedido, set[EstadoPedido]] = {
    EstadoPedido.PEDIDO: {
        EstadoPedido.EN_PROCESO,
        EstadoPedido.CANCELADO,
        EstadoPedido.PENDIENTE_CONFIRMACION,
    },
    EstadoPedido.PENDIENTE_CONFIRMACION: {
        EstadoPedido.PEDIDO,
        EstadoPedido.EN_PROCESO,
        EstadoPedido.CANCELADO,
    },
    EstadoPedido.EN_PROCESO: {
        EstadoPedido.ENTREGADO,
        EstadoPedido.CANCELADO,
    },
    EstadoPedido.ENTREGADO: set(),
    EstadoPedido.CANCELADO: set(),
}


def valid_next_states(current_state: EstadoPedido) -> set[EstadoPedido]:
    return VALID_ORDER_TRANSITIONS[current_state].copy()


def assert_valid_order_transition(current_state: EstadoPedido, next_state: EstadoPedido) -> None:
    if next_state not in VALID_ORDER_TRANSITIONS[current_state]:
        raise ValidationError(
            f"Transicion invalida de {current_state.value} a {next_state.value}."
        )
