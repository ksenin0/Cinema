"""Booking endpoints authorize objects before invoking atomic business operations."""

from django.db.models import QuerySet
from django.http import HttpResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.exports import render_qr_png, render_ticket_pdf, render_ticket_png
from bookings.gateways import get_payment_gateway
from bookings.models import Order, Ticket
from bookings.serializers import (
    BookingInputSerializer,
    CashSaleInputSerializer,
    CheckInSerializer,
    OrderSerializer,
    PaymentInputSerializer,
    PaymentSerializer,
    TicketSerializer,
)
from bookings.services import (
    cancel_order,
    check_in_ticket,
    confirm_refund,
    create_booking,
    create_cash_sale,
    expire_orders,
    record_payment,
)
from common.exceptions import Conflict
from common.permissions import CashierPermission, has_role


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Customer order history with personnel-only payment and refund operations."""

    serializer_class = OrderSerializer

    def get_queryset(self) -> QuerySet:
        """Restrict customer access to owned orders and update expired hold state."""
        expire_orders()
        queryset = Order.objects.select_related("payment").prefetch_related(
            "tickets__seat", "tickets__session__movie", "tickets__session__hall"
        )
        return (
            queryset
            if has_role(self.request.user, "cashier", "admin")
            else queryset.filter(user=self.request.user)
        )

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Validate selected identifiers and create a server-priced ten-minute hold."""
        serializer = BookingInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = create_booking(request.user, **serializer.validated_data)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Cancel an owned pending order, or request a refund when called by personnel."""
        order = cancel_order(
            self.get_object().pk, allow_paid=has_role(request.user, "cashier", "admin")
        )
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"], permission_classes=[CashierPermission])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """Record payment confirmed by the cashier; clients cannot mark orders paid."""
        order = self.get_object()
        serializer = PaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paid = record_payment(order.pk, actor=request.user, **serializer.validated_data)
        return Response(OrderSerializer(paid).data)

    @action(detail=True, methods=["post"], url_path="online-payment")
    def online_payment(self, request: Request, pk: str | None = None) -> Response:
        """Simulate online payment of an accessible order and return its issued tickets."""
        order = self.get_object()
        paid = get_payment_gateway().initiate(order)
        return Response(OrderSerializer(paid).data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[CashierPermission],
        url_path="confirm-refund",
    )
    def refund(self, request: Request, pk: str | None = None) -> Response:
        """Record a manual refund only after a paid order has been cancelled."""
        payment = confirm_refund(self.get_object().pk)
        return Response(PaymentSerializer(payment).data)


class CashSaleView(APIView):
    """Cashier-only walk-in ticket sale without creating a fictitious client account."""

    permission_classes = [CashierPermission]

    def post(self, request: Request) -> Response:
        """Create tickets and record cash/terminal payment in one transaction."""
        serializer = CashSaleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = create_cash_sale(request.user, **serializer.validated_data)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """Owned ticket details and protected electronic ticket downloads."""

    serializer_class = TicketSerializer

    def get_queryset(self) -> QuerySet:
        """Only personnel can read other customers' electronic tickets."""
        queryset = Ticket.objects.select_related("order", "seat", "session__movie", "session__hall")
        return (
            queryset
            if has_role(self.request.user, "cashier", "admin")
            else queryset.filter(order__user=self.request.user)
        )

    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Export a valid paid ticket as PNG, QR PNG, or PDF; reject other formats."""
        ticket = self.get_object()
        if not ticket.is_active or ticket.order.status != Order.Status.PAID:
            raise Conflict("Скачать можно только действующий оплаченный билет.")
        export_format = request.query_params.get("export", "pdf")
        renderers = {
            "pdf": (render_ticket_pdf, "application/pdf", "pdf"),
            "png": (render_ticket_png, "image/png", "png"),
            "qr": (render_qr_png, "image/png", "png"),
        }
        if export_format not in renderers:
            raise ValidationError({"export": "Допустимы pdf, png, qr."})
        renderer, content_type, extension = renderers[export_format]
        response = HttpResponse(renderer(ticket), content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="ticket-{ticket.pk}.{extension}"'
        response["Cache-Control"] = "no-store"
        return response


class CheckInView(APIView):
    """Personnel entry point for validating and consuming a signed QR ticket."""

    permission_classes = [CashierPermission]

    def post(self, request: Request) -> Response:
        """Return the consumed ticket or a standard conflict for a repeated scan."""
        serializer = CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = check_in_ticket(serializer.validated_data["payload"])
        return Response(TicketSerializer(ticket).data)
