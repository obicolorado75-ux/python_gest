"""commandes clients et livraisons

Ajoute les colonnes manquantes du circuit commande → préparation → livraison
(§5.10) : tarif/remise/adresse sur la commande, reliquat par ligne, préparation
et livraison effectives, preuve et encaissement à la livraison.

Revision ID: 97151b198b7d
Revises: 75b49f9d7032
Create Date: 2026-11-16 17:04:05.864256
"""
import sqlalchemy as sa
from alembic import op

revision = '97151b198b7d'
down_revision = '75b49f9d7032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('customer_order_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit_label', sa.String(length=60),
                                      nullable=False, server_default='Unité'))
        batch_op.add_column(sa.Column('reserved_qty', sa.Integer(),
                                      nullable=False, server_default='0'))

    with op.batch_alter_table('customer_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('price_list_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('discount_amount', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('address', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('cancelled_reason', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_customer_orders_price_list_id',
                                    'price_lists', ['price_list_id'], ['id'])

    with op.batch_alter_table('deliveries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prepared_qty', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('delivered_qty', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('delivered_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('failure_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('collected_amount', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('payment_method', sa.String(length=40),
                                      nullable=True))
        batch_op.create_index(batch_op.f('ix_deliveries_status'), ['status'],
                              unique=False)

    with op.batch_alter_table('delivery_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('order_line_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('packaging_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('designation', sa.String(length=200),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('unit_label', sa.String(length=60),
                                      nullable=False, server_default='Unité'))
        batch_op.add_column(sa.Column('quantity_display', sa.Integer(),
                                      nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('unit_price', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.create_foreign_key('fk_delivery_lines_packaging_id',
                                    'product_packagings', ['packaging_id'], ['id'])
        batch_op.create_foreign_key('fk_delivery_lines_order_line_id',
                                    'customer_order_lines', ['order_line_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('delivery_lines', schema=None) as batch_op:
        batch_op.drop_constraint('fk_delivery_lines_order_line_id',
                                 type_='foreignkey')
        batch_op.drop_constraint('fk_delivery_lines_packaging_id',
                                 type_='foreignkey')
        batch_op.drop_column('unit_price')
        batch_op.drop_column('quantity_display')
        batch_op.drop_column('unit_label')
        batch_op.drop_column('designation')
        batch_op.drop_column('packaging_id')
        batch_op.drop_column('order_line_id')

    with op.batch_alter_table('deliveries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deliveries_status'))
        batch_op.drop_column('payment_method')
        batch_op.drop_column('collected_amount')
        batch_op.drop_column('failure_reason')
        batch_op.drop_column('delivered_at')
        batch_op.drop_column('delivered_qty')
        batch_op.drop_column('prepared_qty')

    with op.batch_alter_table('customer_orders', schema=None) as batch_op:
        batch_op.drop_constraint('fk_customer_orders_price_list_id',
                                 type_='foreignkey')
        batch_op.drop_column('cancelled_reason')
        batch_op.drop_column('address')
        batch_op.drop_column('discount_amount')
        batch_op.drop_column('price_list_id')

    with op.batch_alter_table('customer_order_lines', schema=None) as batch_op:
        batch_op.drop_column('reserved_qty')
        batch_op.drop_column('unit_label')
