from app.models import Customer, Deal, Task
from app.services.dto import CustomerDTO, DealDTO, TaskDTO


def customer_to_dto(customer: Customer) -> CustomerDTO:
    return CustomerDTO(
        id=customer.id,
        uuid=customer.uuid,
        name=customer.name,
        company_name=customer.company_name,
        phone=customer.phone,
        email=customer.email,
        telegram=customer.telegram,
        position=customer.position,
        notes=customer.notes,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def deal_to_dto(deal: Deal) -> DealDTO:
    return DealDTO(
        id=deal.id,
        uuid=deal.uuid,
        title=deal.title,
        customer_id=deal.customer_id,
        customer_name=deal.customer.name,
        amount=deal.amount,
        stage=deal.stage,
        description=deal.description,
        expected_close_date=deal.expected_close_date,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )


def task_to_dto(task: Task) -> TaskDTO:
    return TaskDTO(
        id=task.id,
        uuid=task.uuid,
        title=task.title,
        description=task.description,
        customer_id=task.customer_id,
        customer_name=task.customer.name if task.customer else "",
        deal_id=task.deal_id,
        deal_title=task.deal.title if task.deal else "",
        due_date=task.due_date,
        priority=task.priority,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )

