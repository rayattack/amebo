'''
create table tasks (
    id int primary key,
    task text,
    owner_id int references owners(id),  -- owner can be person or group
    unique(id, owner_id)
);


create table if not exists tasks_arrangement (
    owner_id int references owners(id),
    task_id int references tasks(id),
    after int references tasks(id),
    foreign key (task_id, owner_id) references tasks(id, owner_id),
    unique(task_id, after_id)
);
'''


async def reorder(req, res, ctx):
    op = ctx.op
    table = 'tasks_arrangements'

    item_being_moved = req.params.get('id:int')
    moved_after_item = ctx.form.after

    # select item behind item being moved to set it's after to item_being_moved's after
    item_being_moved_follower = ...  # select item from table where after = item_being_moved
    first = op.execute(f'update {table} set after = {item_being_moved.after} where id = {item_being_moved_follower.task_id} and owner_id = {ctx.profile.id}')

    # select item behind moved_after_item so we can change it's after to item_being_moved
    moved_after_item_follower = ...  # select item from table where after = moved_after_item
    second = op.execute(f'update {table} set after = {item_being_moved.id} where id = {moved_after_item_follower.task_id} and owner_id = {ctx.profile.id}')

    # then finally change item_being_moved's after to moved_after_item
    third = op.execute(f'update {table} set after = {moved_after_item.id} where id = {item_being_moved_follower.task_id} and owner_id = {ctx.profile.id}')

    op.transactions.add(first, second, third)
    await op.run()


async def order(req, res, ctx):
    rows = await ctx.op.execute(f'''
        select t.id, t.task, a.after
        from tasks t
        join tasks_arrangement a
        on a.task_id = t.id
        where owner_id = 100
        order by a.after
    ''').run()
